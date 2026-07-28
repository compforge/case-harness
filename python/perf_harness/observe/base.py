"""Probe — the observation extension point (the other plug-in axis).

A Probe samples one Source on a fixed interval and contributes one or more named
Metrics; each Metric becomes a time-series within the Trial, and the Probe also
says how to collapse its own series into the summary row (``summarize``).

"Source" is just *which handle on the ProbeContext a Probe reads*: the http
client (scrape any /metrics), the client-side ClientStats (load generator's own
view), or the Subject's K8s coordinates (see ``k8s.py``). Decoupling the
Source from the Subject is what lets one run mix client-side + server-side +
downstream probes and so attribute a slowdown rather than guess.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from perf_harness.metric import (
    MetricFamily,
    MetricSummary,
    MetricValueKind,
    series_id,
)
from perf_harness.metric.reduce import time_series_summary
from perf_harness.model import ProbeErrors, Sample, Target


class ClientStats:
    """Load-generator-side counters, updated by the Engine around each fire."""

    def __init__(self) -> None:
        self.inflight = 0
        self.sent = 0

    def start(self) -> None:
        self.inflight += 1
        self.sent += 1

    def done(self) -> None:
        self.inflight -= 1


@dataclass
class ProbeContext:
    """The handles a Probe may read from — each field is a candidate Source.

    ``client`` is the *load* client (also handed to ``Workload.fire``).
    ``observer_client`` is a separate client with its own small pool that
    HTTP-source probes (e.g. ``/metrics`` scrape) must use, so observation does
    NOT queue behind load traffic on a saturated pool — which is exactly when
    server-side evidence matters most. Falls back to ``client`` when unset.
    """

    target: Target
    client: httpx.AsyncClient
    t0: float
    stats: ClientStats = field(default_factory=ClientStats)
    observer_client: httpx.AsyncClient | None = None

    @property
    def probe_client(self) -> httpx.AsyncClient:
        """The client HTTP-source probes should read (isolated from load)."""
        return self.observer_client or self.client


@dataclass(frozen=True)
class FamilySpec:
    """One bare metric a Probe emits — unit + value_kind + human meaning, declared
    ONCE in the probe's ``families`` table (the mdatagen idea: metric metadata is a
    single declarative table that recording, registry and docs all read)."""

    unit: str
    value_kind: MetricValueKind = "gauge"
    description: str = ""
    labels: tuple[str, ...] = ()


class Probe(ABC):
    """Samples a Source over time and collapses its series for the summary row.

    A Probe is the ``resource`` side of perf's one metric model: it speaks the
    same unified ``Metric`` vocabulary the request side does (see ``describe``), so
    a cpu gauge and a per-request ttft are both "metrics", differing only in side.
    """

    #: stable, UNIQUE store id (one per observed target, e.g. "top.chat"); the
    #: metric *family* is the class-level name ("top") and ``service`` is a label.
    name: str = "probe"
    #: where this probe reads — groups its metrics for bottleneck attribution
    source: str = ""
    #: which service this probe observes (a downstream entry / the Subject); the
    #: family stays un-prefixed and ``service`` becomes a label on every metric.
    _service: str | None = None

    @property
    def family(self) -> str:
        """The metric family (un-prefixed) — the class-level ``name``. Service-bound
        instances suffix ``self.name`` (for a unique store id) but keep this family."""
        return type(self).name

    @property
    def labels(self) -> dict[str, str]:
        """Series labels — ``{service: …}`` when bound to a service, else none."""
        return {"service": self._service} if self._service else {}

    #: THE declaration table: bare metric name → its FamilySpec (unit + value_kind +
    #: description). One source of truth for ``describe`` (the registry descriptor),
    #: ``summarize`` (which reducers to emit) and the Engine (series units) — a
    #: single table, so the vocabularies can't drift apart.
    families: dict[str, FamilySpec] = {}

    def describe(self) -> list[MetricFamily]:
        """This probe's contributions as ``resource``-side metric FAMILIES (no labels).

        The seam that makes a Probe part of the one metric model: its series are
        ``resource`` metrics, addressed ``<name>{labels}.<stat>`` in the report/SLO
        exactly like the request-side metrics a Workload records on the Outcome. The
        family is label-free (``top.cpu_m``); ``service`` is a label on the concrete
        series (built in the Engine from ``self.labels``), so two service-bound probes
        of the same family dedup to one family entry instead of duplicating metadata.
        """
        return [
            MetricFamily(
                name=f"{self.family}.{m}",  # family (top.cpu_m); service is a series label
                unit=spec.unit,
                side="resource",
                value_kind=spec.value_kind,
                source=self.source,
                description=spec.description,
                labels=frozenset((*self.labels, *spec.labels)),
            )
            for m, spec in self.families.items()
        ]

    @abstractmethod
    async def sample(self, ctx: ProbeContext) -> dict[str, float]:
        """One instantaneous reading. Omit a key when it is momentarily unavailable.

        A key is normally the bare metric name (one series at the probe's base
        ``labels``). A probe observing multiple instances may key a value with extra
        labels in ``series_id`` form (``cpu_m{pod="…"}``) — one series per instance,
        merged onto the base labels. Same metric model either way: a label is part of
        the series identity, and the Engine/report group by it like any other label."""

    def summarize(self, series: dict[str, list[Sample]]) -> dict[str, MetricSummary]:
        """Collapse this probe's (steady-state) series → one typed MetricSummary per
        (bare) metric, keyed by bare name (the Engine prefixes ``<probe>.``).

        ``value_kind`` (from ``families``) picks the reducer: gauge → mean/peak/last,
        counter → total/rate/increase (rate = Δ/Δt over the steady window). One
        impl covers every built-in probe; override only for an exotic reduction.
        """
        out: dict[str, MetricSummary] = {}
        for metric, samples in series.items():
            spec = self.families.get(metric)
            summary = time_series_summary(samples, spec.value_kind if spec is not None else "gauge")
            if summary is not None:
                out[metric] = summary
        return out


class ClientProbe(Probe):
    """Client-side Source: in-flight depth and total sent, no external call."""

    name = "client"
    source = "client"
    families = {
        "inflight": FamilySpec("count", "gauge", "requests in flight from the load generator"),
        "sent": FamilySpec("count", "counter", "total requests the load generator has sent"),
    }

    async def sample(self, ctx: ProbeContext) -> dict[str, float]:
        return {"inflight": float(ctx.stats.inflight), "sent": float(ctx.stats.sent)}


@dataclass
class ScrapeSpec:
    """One EXTRA Prometheus sample family to scrape off the Subject's ``/metrics``.

    The generic seam for app-specific server metrics (e.g. the GenAI SSE hooks):
    ``source`` is the exposition SAMPLE name — for a histogram scrape the suffixed
    series (``…_count`` / ``…_sum``) as counters; Δsum ÷ Δcount over the steady
    window is then the server-side mean. ``match`` keeps only label sets equal on
    the given keys; ``drop`` removes label sets whose value is listed (e.g.
    ``error_type`` in ``("", "client_disconnect")``). The sampled value is the SUM
    over surviving label sets, recorded under the bare metric ``name``.

    ``by`` keeps one series per distinct value of the listed labels instead
    (PromQL's ``sum by (path) (…)``): keys go out in ``series_id`` form
    (``name{path="…"}``) and the Engine groups/reports them like ``per_pod``
    series — no per-value config entries needed. match/drop filter FIRST, then
    ``by`` groups the survivors. Cardinality is the declarer's responsibility:
    ``by`` a bounded label (route path, status class), never a free-form one
    (user id, conversation id) — every distinct value becomes a full series.
    """

    source: str
    name: str
    value_kind: MetricValueKind = "counter"
    unit: str = "count"
    description: str = ""
    match: dict[str, str] = field(default_factory=dict)
    drop: dict[str, tuple[str, ...]] = field(default_factory=dict)
    by: tuple[str, ...] = ()


@dataclass
class DeriveSpec:
    """A per-trial DERIVED scalar: the ratio of two counter families' steady-window
    increases — a top-level ``derived:`` entry, evaluated at reduce time from the
    already-collected series (collection itself stays dumb).

    The Prometheus-histogram idiom made declarative: ``mean = Δ…_sum ÷ Δ…_count`` —
    "did server-side ttft grow with pressure" becomes one response-curve point per
    trial. ``num``/``den`` are counter FAMILY names (``metrics.sse_ttft_sum``); the
    ratio is computed per label set where both exist (so a per-service or ``by:``
    fan-out derives one ratio per series, automatically). The result registers as
    family ``name`` (``side="resource"``, ``value_kind="scalar"``, addressed
    ``<name>{service=…}.value``). Computed from reset-aware increases, and
    observational like everything scraped — it gates nothing unless an SLO
    explicitly references it.
    """

    name: str
    num: str
    den: str
    unit: str = ""
    description: str = ""


class MetricsScrapeProbe(Probe):
    """Http Source: scrape the Subject's Prometheus ``/metrics`` over time.

    Tracks the request counter (collapsed to server-observed RPS) and the
    in-progress gauge (collapsed to peak). The ``prefix`` defaults to the
    Subject's ``K8sRef.metrics_prefix`` (starlette_exporter prefix). ``scrape``
    adds arbitrary exposition families (``ScrapeSpec``) — they enter the same
    metric model (``metrics.<name>{service=…}``), so report/SLO/analysis see them
    like any builtin.
    """

    name = "metrics"
    source = "http"
    families = {
        "req_total": FamilySpec("count", "counter", "server-side request counter (from /metrics)"),
        "in_progress": FamilySpec(
            "count", "gauge", "server-side in-progress requests (from /metrics)"
        ),
    }

    def __init__(
        self,
        *,
        prefix: str | None = None,
        path: str = "/metrics",
        service: str | None = None,
        scrape: list[ScrapeSpec] | None = None,
        url: str | None = None,
    ) -> None:
        self._prefix = prefix
        self._path = path
        self._service = service
        # public: config's top-level `derived:` validation reads the by-groupings
        self.scrape = list(scrape or [])
        # explicit exposition URL (convention: http://<service-ip>:<port>/metrics) —
        # unbinds the probe from the Subject so downstream services' /metrics are
        # observable too; None → the Subject's base_url + path (the default).
        self._url = url
        # per-instance vocabulary: scraped extras join the SAME declaration table the
        # builtins live in, so describe()/summarize() see them like builtins
        self.families = {
            **type(self).families,
            **{s.name: FamilySpec(s.unit, s.value_kind, s.description, s.by) for s in self.scrape},
        }
        if service:  # unique store id (metrics.chat); family stays "metrics", service is a label
            self.name = f"{self.name}.{service}"

    def _resolve_prefix(self, ctx: ProbeContext) -> str | None:
        if self._prefix:
            return self._prefix
        return ctx.target.k8s.metrics_prefix if ctx.target.k8s else None

    def _specs(self, prefix: str | None) -> list[ScrapeSpec]:
        """Everything this probe scrapes, as ONE vocabulary: the two builtins are just
        canned ScrapeSpecs for the starlette_exporter naming convention — a soft
        default (absent family → key omitted), not a coupling; ``scrape`` adds the
        rest through the same path."""
        builtin = (
            [
                ScrapeSpec(source=f"{prefix}_requests_total", name="req_total"),
                ScrapeSpec(
                    source=f"{prefix}_requests_in_progress",
                    name="in_progress",
                    value_kind="gauge",
                ),  # fmt: skip
            ]
            if prefix
            else []
        )
        return builtin + self.scrape

    async def sample(self, ctx: ProbeContext) -> dict[str, float]:
        specs = self._specs(self._resolve_prefix(ctx))
        if not specs:
            return {}
        url = self._url or ctx.target.base_url.rstrip("/") + self._path
        # scrape etiquette per the reference consumer (Prometheus's targetScraper):
        # pin the classic text format via Accept (a content-negotiating endpoint must
        # not hand us OpenMetrics/protobuf) and identify ourselves.
        headers = {
            "Accept": "text/plain;version=0.0.4",
            "User-Agent": "perf-harness-scrape",
        }
        r = await ctx.probe_client.get(url, headers=headers, timeout=5.0)
        # a 500/404 body must NOT be parsed as "no data" — raise so the Engine records
        # a probe_error (observability failure is a fact, not an empty reading)
        r.raise_for_status()
        out: dict[str, float] = {}
        for spec in specs:
            if spec.by:
                # one series per distinct by-label value (series_id keys) — the
                # Engine groups labeled keys per extra-label-set like per_pod
                groups = prom_sum_by(r.text, spec.source, spec.by, match=spec.match, drop=spec.drop)
                for vals, v in (groups or {}).items():
                    out[series_id(spec.name, dict(zip(spec.by, vals, strict=True)))] = v
            else:
                v = prom_sum_where(r.text, spec.source, match=spec.match, drop=spec.drop)
                if v is not None:
                    out[spec.name] = v
        return out


def _parse_label_block(s: str) -> tuple[dict[str, str] | None, str]:
    """Parse the inside of an exposition label block (after ``{``) → (labels, rest
    after ``}``); ``(None, "")`` on malformed input. Quote-aware per the text format
    spec (mirrors Prometheus's own parser): a quoted value may contain commas and the
    escapes ``\\\\``, ``\\"``, ``\\n`` — a naive split-on-comma corrupts those."""
    labels: dict[str, str] = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i] in ", \t":  # separators between pairs
            i += 1
        if i < n and s[i] == "}":
            return labels, s[i + 1 :]
        j = i
        while j < n and s[j] not in "=}":
            j += 1
        if j >= n or s[j] != "=":
            return None, ""
        key = s[i:j].strip()
        i = j + 1
        if i >= n or s[i] != '"':
            return None, ""
        i += 1
        buf: list[str] = []
        while i < n and s[i] != '"':
            c = s[i]
            if c == "\\" and i + 1 < n:
                nxt = s[i + 1]
                buf.append({"n": "\n", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
                i += 2
                continue
            buf.append(c)
            i += 1
        if i >= n:  # unterminated value
            return None, ""
        labels[key] = "".join(buf)
        i += 1
    return None, ""  # no closing brace


def _parse_prom_line(raw: str) -> tuple[str, dict[str, str], float] | None:
    """One exposition line → ``(sample_name, labels, value)``; None for comments /
    unparseable lines. Shape: ``name[{labels}] value [timestamp]`` — the optional
    trailing timestamp is ignored (we stamp our own sampling time)."""
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if "{" in line:
        name, _, rest = line.partition("{")
        labels, tail = _parse_label_block(rest)
        if labels is None:
            return None
    else:
        name, _, tail = line.partition(" ")
        labels = {}
    parts = tail.split()
    if not parts:
        return None
    try:
        value = float(parts[0])  # the spec's +Inf/NaN parse natively
    except ValueError:
        return None
    return name.strip(), labels, value


def prom_sum(text: str, name: str) -> float | None:
    """Sum a Prometheus sample family across ALL its label sets. None if absent."""
    return prom_sum_where(text, name)


def prom_sum_where(
    text: str,
    name: str,
    *,
    match: dict[str, str] | None = None,
    drop: dict[str, tuple[str, ...]] | None = None,
) -> float | None:
    """Sum a sample family across the label sets that pass the filters.

    ``match``: keep a line only if every given label equals its value. ``drop``:
    discard a line if a given label's value is in the listed values. Returns None
    only when the FAMILY is absent from the exposition; present-but-all-filtered
    sums to 0.0 (so a counter rate stays well-defined, e.g. zero errors so far).
    """
    total = 0.0
    seen = False
    for raw in text.splitlines():
        parsed = _parse_prom_line(raw)
        if parsed is None or parsed[0] != name:
            continue
        seen = True
        _, labels, value = parsed
        if match and any(labels.get(k) != v for k, v in match.items()):
            continue
        if drop and any(labels.get(k) in vals for k, vals in drop.items()):
            continue
        total += value
    return total if seen else None


def prom_sum_by(
    text: str,
    name: str,
    by: tuple[str, ...],
    *,
    match: dict[str, str] | None = None,
    drop: dict[str, tuple[str, ...]] | None = None,
) -> dict[tuple[str, ...], float] | None:
    """Group-and-sum a sample family by the ``by`` labels' values (PromQL's
    ``sum by (…)``), after the same match/drop filters as ``prom_sum_where``.

    Keys are the ``by`` labels' values in declaration order; a label absent from
    a line reads as ``""`` (it still forms a group — same as PromQL). Returns
    None only when the FAMILY is absent from the exposition; present-but-all-
    filtered is an empty dict (no groups, vs prom_sum_where's well-defined 0.0 —
    a group that never existed has no counter to keep alive).
    """
    groups: dict[tuple[str, ...], float] = {}
    seen = False
    for raw in text.splitlines():
        parsed = _parse_prom_line(raw)
        if parsed is None or parsed[0] != name:
            continue
        seen = True
        _, labels, value = parsed
        if match and any(labels.get(k) != v for k, v in match.items()):
            continue
        if drop and any(labels.get(k) in vals for k, vals in drop.items()):
            continue
        key = tuple(labels.get(k, "") for k in by)
        groups[key] = groups.get(key, 0.0) + value
    return groups if seen else None


# Probe sample store: (probe.name, sample key) → time series. The sample key is what
# ``Probe.sample`` returned it under — a bare metric (``cpu_m``) or, for a fan-out
# probe, a labeled ``series_id`` (``cpu_m{pod="…"}``). Tupling with the unique
# probe.name (instead of concatenating) keeps "top" / "top.chat" keys collision-free.
ProbeStore = dict[tuple[str, str], list[Sample]]


async def observe_loop(
    probes: list[Probe],
    ctx: ProbeContext,
    store: ProbeStore,
    stop: asyncio.Event,
    interval: float,
) -> dict[str, ProbeErrors]:
    """Sample every probe each ``interval`` until stopped. A failing probe never stops
    observation, but the failure is RECORDED, not swallowed — returns the per-probe
    error census (failures / total ticks / last error) so ``_aggregate`` can flag the
    affected summaries and the trial. A broken /metrics must not render as calm data."""
    failures: dict[str, list[str]] = {}
    ticks = 0
    while True:
        t = time.monotonic() - ctx.t0
        ticks += 1
        for probe in probes:
            try:
                reading = await probe.sample(ctx)
            except Exception as exc:  # noqa: BLE001 — one bad probe must not stop observation
                failures.setdefault(probe.name, []).append(repr(exc))
                reading = None
            # synthesize the probe's health as a SERIES (the Prometheus `up` analogue):
            # the trial census says THAT observation broke, this says WHEN — §4 can
            # chart the outage window instead of a fake-calm gap. 1 ok / 0 failed.
            store.setdefault((probe.name, "up"), []).append(
                Sample(t, 0.0 if reading is None else 1.0)
            )
            for key, val in (reading or {}).items():
                store.setdefault((probe.name, key), []).append(Sample(t, val))
        if stop.is_set():
            break
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
    return {
        name: ProbeErrors(failures=len(errs), ticks=ticks, last=errs[-1])
        for name, errs in failures.items()
    }
