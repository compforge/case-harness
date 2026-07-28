"""MetricStore — the one addressable read face over a run's trials.

A run is a response surface: ``metric = f(resources, load, slice)``. The store IS
that surface as an index — every report/SLO-visible number is addressable
``<family>{labels}.<stat>`` and resolved here, regardless of which side
(``request`` / ``resource``) it lives on or how it was produced.

The store is the **addressing layer over the slice storage** (the perf analogue of
TSDB vs PromQL), so the boundary is:
  - SLO + capacity read ONLY through the store (``query`` / ``rows``) — one source for
    every gated number, so a gate can't diverge from the report on how it's computed.
  - the report renders ``RequestStats`` request-slices *directly* for its hot stat
    columns (n / p50 / p99 …) — that's the slice's reduced storage, not a different
    computation — and uses the store (``pivot``) for label-routed resource reads (the
    per-service pivot). It does not round-trip the hot columns through ``query`` (pure
    indirection, no divergence to prevent).

``query`` returns ``Read`` = ``float | Missing`` — absence is a value, not a bare
``None``, so an SLO maps it to *skipped* (never silently to pass). service / facet /
stage are all just labels; the resolver routes on them (``{service=…}`` → the
trial-global resource metric; a facet/stage label → that request slice; none → overall).

The builtin descriptors + the request-slice projection live here too (they ARE the
metric layer); ``slo.py`` and ``config.py`` import them from here.
"""

from __future__ import annotations

from perf_harness.metric import (
    DistributionSummary,
    MetricFamily,
    MetricSummary,
    Missing,
    Read,
    ScalarSummary,
    parse_ref,
    resolve,
    series_id,
)
from perf_harness.metric.reduce import time_series_summary
from perf_harness.model import RequestStats, TrialResult

# builtin request-side metric families (aggregated from judged Outcomes) — always
# present, registered so an SLO may gate them and the report can describe them.
REQUEST_DESCRIPTORS: list[MetricFamily] = [
    MetricFamily(
        "request.duration_ms",
        "ms",
        "request",
        "distribution",
        "client",
        description="end-to-end request latency, client-observed",
    ),
    MetricFamily(
        "request.error_rate",
        "ratio",
        "request",
        "scalar",
        "client",
        description="judged failures ÷ sent requests (Workload.judge)",
    ),
    MetricFamily(
        "request.throughput_rps",
        "rps",
        "request",
        "scalar",
        "client",
        description="completed requests ÷ steady window",
    ),
    MetricFamily(
        "request.drop_rate",
        "ratio",
        "request",
        "scalar",
        "client",
        description="open-loop client_saturated drops ÷ offered (not latency samples)",
    ),
]

# framework-recorded per-request metrics (stream_sse always records ttft_ms) — declared
# so an SLO may gate them. A consumer's OWN per-request metrics (first_<event>_ms …) are
# undeclared by default → they reach the report/CSV but cannot gate unless the Workload
# declares them via describe() (an SLO must fail-fast, not silently skip a typo).
PER_REQUEST_DESCRIPTORS: list[MetricFamily] = [
    MetricFamily(
        "ttft_ms",
        "ms",
        "request",
        "distribution",
        "client",
        description="time to first SSE byte/event, per request",
    ),
]

# undotted builtin RequestStats fields usable directly as SLO metrics (aliases)
SLO_METRICS = frozenset(
    {
        "n",
        "n_ok",
        "n_dropped",
        "throughput_rps",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "error_rate",
        "drop_rate",
    }
)


def slice_summaries(sl: RequestStats) -> dict[str, MetricSummary]:
    """A request slice's unified metric summaries: its per_request distributions plus
    the builtin derived ``request.*`` (delegating to the slice's typed fields). The
    slice's caveats ride on its ``request.duration_ms`` distribution, so a CO-biased /
    saturated latency is never read as clean."""
    out: dict[str, MetricSummary] = dict(sl.metrics)
    out["request.duration_ms"] = DistributionSummary(
        n=sl.n, mean=sl.mean_ms, p50=sl.p50_ms, p95=sl.p95_ms, p99=sl.p99_ms, caveats=sl.caveats
    )
    out["request.error_rate"] = ScalarSummary(sl.error_rate)
    out["request.throughput_rps"] = ScalarSummary(sl.throughput_rps)
    out["request.drop_rate"] = ScalarSummary(sl.drop_rate)
    return out


class MetricStore:
    """Addressable read face over a run's trials (see module docstring)."""

    def __init__(self, trials: list[TrialResult]) -> None:
        self._trials = trials
        self._families: dict[str, MetricFamily] = {}
        for t in trials:
            self._families.update(t.metrics)

    def rows(self) -> list[TrialResult]:
        return self._trials

    def families(self) -> dict[str, MetricFamily]:
        return self._families

    def family(self, name: str) -> MetricFamily | None:
        return self._families.get(name)

    def query(self, trial: TrialResult, ref: str) -> Read:
        """Resolve a metric ref on one trial → its value, or a ``Missing`` (with reason).

        ``service`` label → the trial-global resource metric; ``stage`` / a facet
        label → that request slice; no labels → overall (which also exposes the
        unlabeled resource metrics). An undotted ``name`` is a builtin RequestStats
        alias (``p99_ms`` / ``error_rate`` / …)."""
        name, labels, stat = parse_ref(ref)
        family = trial.metrics.get(name) or self._families.get(name)
        if family is not None and family.side == "resource":
            if stat is None:
                return Missing("no_data")
            val = resolve(trial.probe_metrics, ref)
            if val is not None:
                return val
            return self._resource_missing(trial, name, labels)
        sl = self._request_slice(trial, labels)
        if sl is None:
            return Missing("no_slice")
        if stat is None:  # undotted builtin RequestStats field
            v = getattr(sl, name, None)
            return float(v) if v is not None else Missing("no_data")
        summaries = slice_summaries(sl)
        if not labels:  # overall also exposes the trial-global (unlabeled) resource metrics
            summaries = {**trial.probe_metrics, **summaries}
        v = resolve(summaries, f"{name}.{stat}")
        return v if v is not None else Missing("no_data")

    def query_window(self, trial: TrialResult, ref: str, *, start_s: float) -> Read:
        """Resolve a resource metric from raw samples at/after ``start_s``.

        This is the same address and reducer used by the measurement summary, but
        against a different time window. Request distributions and derived scalars
        have no raw time-sampled series and are rejected at config time.
        """
        name, labels, stat = parse_ref(ref)
        family = trial.metrics.get(name) or self._families.get(name)
        if family is None or family.side != "resource" or stat is None:
            return Missing("no_data")
        health_labels = {"service": labels["service"]} if "service" in labels else {}
        health_sid = series_id(f"{name.split('.', 1)[0]}.up", health_labels)
        health = trial.series.get(health_sid)
        health_samples = (
            [sample for sample in health.samples if sample.t >= start_s] if health else []
        )
        if not health_samples or any(sample.value <= 0 for sample in health_samples):
            return Missing("probe_error")
        raw = trial.series.get(series_id(name, labels))
        if raw is None:
            return self._resource_missing(trial, name, labels)
        samples = [sample for sample in raw.samples if sample.t >= start_s]
        # A labeled series may disappear while its probe still succeeds. Requiring
        # a value on the probe's final cooldown tick prevents `.last` from reading a
        # stale pre-scale-down sample as a successful final state.
        if not samples or samples[-1].t < health_samples[-1].t:
            return Missing("probe_error")
        summary = time_series_summary(samples, family.value_kind)
        if summary is None:
            return Missing("no_data")
        value = resolve({series_id(name, labels): summary}, ref)
        return value if value is not None else Missing("no_data")

    def summary(self, trial: TrialResult, sid: str) -> MetricSummary | None:
        """The typed summary for a concrete series id (no stat) on a trial, or None —
        e.g. ``top.cpu_m{service="chat"}`` → that GaugeSummary (with its caveats)."""
        name, labels, _ = parse_ref(sid)
        if "service" in labels:
            return trial.probe_metrics.get(sid)
        sl = self._request_slice(trial, labels)
        if sl is None:
            return None
        return slice_summaries(sl).get(name)

    def pivot(self, trial: TrialResult, family: str, by: str) -> dict[str, MetricSummary]:
        """Group a family's series by the single label ``by`` → ``{label_value: summary}``.

        Today used for the resource ``by="service"`` pivot — the request side pivots
        by_facet/by_stage on ``RequestStats`` directly. Same "group by label" idea
        either way."""
        out: dict[str, MetricSummary] = {}
        for sid, summ in trial.probe_metrics.items():
            name, labels, _ = parse_ref(sid)
            if name != family or by not in labels:
                continue
            # the common case has exactly the `by` label (one series per service). A
            # fan-out probe adds more labels (per-pod → {service, pod}); key the column by
            # `by` plus the remaining label values so the pods stay distinct, e.g.
            # "chat/chat-abc". Single-label series are unchanged ("chat").
            extra = [v for k, v in sorted(labels.items()) if k != by]
            out["/".join([labels[by], *extra])] = summ
        return out

    def _request_slice(self, trial: TrialResult, labels: dict[str, str]) -> RequestStats | None:
        """The request-side slice a ref's labels point at: no labels → overall;
        ``{stage:…}`` → a schedule stage; a single facet ``{key:val}`` → that facet
        slice. None if absent on this trial (→ a Missing/no_slice)."""
        if not labels:
            return trial.overall
        if "stage" in labels:
            return trial.by_stage.get(labels["stage"])
        ((key, val),) = labels.items()  # a single facet key=value
        return trial.by_facet.get(key, {}).get(val)

    @staticmethod
    def _resource_missing(trial: TrialResult, name: str, labels: dict[str, str]) -> Missing:
        """Distinguish a broken producing probe from an absent resource series."""
        service = labels.get("service")
        if service is not None:
            probe_id = f"{name.split('.', 1)[0]}.{service}"
            if probe_id in trial.probe_errors:
                return Missing("probe_error")
        return Missing("no_slice" if labels else "no_data")
