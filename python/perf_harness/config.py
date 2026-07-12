"""Config — a YAML run file → an Experiment (+ runs dir).

Keeps the wiring (the subject, which Probes, the resources × load grid)
declarative so a run is reproducible and reviewable. See ``examples/`` for a
filled-in file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import get_args

import yaml
from harness_common.case import Case
from harness_common.facets import FacetSchema
from harness_common.overlay import Overlay

from perf_harness.drive.load import LoadModel, LoadProfile, Pacing, PacingKind, Schedule, Stage
from perf_harness.drive.workload import MockWorkload, Workload, build_workload
from perf_harness.engine import Experiment, Subject
from perf_harness.metric import MetricFamily, parse_ref, validate_ref
from perf_harness.metric.store import PER_REQUEST_DESCRIPTORS, REQUEST_DESCRIPTORS, SLO_METRICS
from perf_harness.model import K8sRef, ResourceProfile, SloAssertion, SloOp, Target
from perf_harness.observe import (
    ClientProbe,
    DeriveSpec,
    KubectlTopProbe,
    MetricsScrapeProbe,
    PerWorkerRSSProbe,
    Probe,
    ResourceLimitsProbe,
    RestartProbe,
    ScrapeSpec,
)
from perf_harness.subject import HelmProvisioner, Provisioner

# valid enum values, derived from the Literal types so they can't drift
_LOAD_MODELS = get_args(LoadModel)
_PACING_KINDS = get_args(PacingKind)
_SLO_OPS = get_args(SloOp)

_PROBES = {
    "client": ClientProbe,
    "metrics": MetricsScrapeProbe,
    "top": KubectlTopProbe,
    "rss": PerWorkerRSSProbe,
    "restart": RestartProbe,
    "limits": ResourceLimitsProbe,
}

# probes that can observe a *downstream* service (read a pod by K8sRef, no URL) —
# the subset allowed under `observe:`. client/metrics need the Subject's handles.
_K8S_PROBES = {"top", "rss", "restart", "limits"}


def load_experiment(path: str, *, mock: bool = False) -> tuple[Experiment, str]:
    """Parse a run file → (Experiment, runs_dir). One config = one named experiment.

    ``mock=True`` swaps in ``MockWorkload`` *instead of* resolving the registry,
    so a real config can be smoke-run offline even when its ``workload.name`` is
    only registered in the consumer project (not importable here).
    """
    raw = yaml.safe_load(Path(path).expanduser().read_text())
    subj = raw["subject"]
    subj_name = subj.get("name", "subject")
    prov_cfg = subj.get("provisioner") or {}
    if prov_cfg.get("type") == "static" or "base_url" in prov_cfg:
        raise ValueError(
            "subject.provisioner.static was removed — reachability lives on the subject: "
            "put base_url/headers/k8s directly under `subject:` and omit `provisioner` "
            "(only `helm` remains, for harness-driven resource sweeps)"
        )
    if "base_url" not in subj:
        raise ValueError("subject needs a `base_url` (how to reach the service)")
    k8s = _parse_k8s(subj.get("k8s"))
    target = Target(base_url=subj["base_url"], headers=subj.get("headers", {}), k8s=k8s)
    provisioner = _parse_provisioner(subj.get("provisioner"), k8s)

    wl_cfg = raw["workload"]
    workload = MockWorkload() if mock else build_workload(wl_cfg["name"], wl_cfg)

    if "constraints" in raw:
        raise ValueError(
            "`constraints:` was renamed `resources:` — the resource profiles "
            "(workers/cpu/memory/replicas) the grid sweeps"
        )
    resources = [_parse_resources(c) for c in raw.get("resources", [{}])]
    loads = _parse_loads(raw["load"])
    if "probes" in raw:
        raise ValueError(
            "`probes:` was removed — `client` is always recorded; put metrics/top/rss/restart "
            "under `observe:` (the Subject is the entry that omits `k8s`)"
        )
    # client (load-gen's own inflight/sent) is harness-intrinsic → always on, not a
    # config knob. observe: is the one place for per-service resource observation.
    probes = [ClientProbe(), *_parse_observe(raw.get("observe"))]
    derived = _parse_derived(raw.get("derived"), probes)
    cases = _parse_cases(raw)
    mix = _parse_mix(raw, cases)
    slo = _parse_slo(raw.get("slo"))
    _validate_producers(probes, workload)
    registry = _static_registry(probes, workload, derived)
    declared_facets = _declared_facet_pairs(raw.get("facets"), cases, workload)
    # observed services close the `{service="…"}` label value space (the family-keyed
    # registry no longer carries a per-service entry to check against)
    declared_services = {p.labels["service"] for p in probes if "service" in p.labels}
    # (family, service) pairs whose series are per-pod ONLY: per_pod emits {pod,service}
    # series and no service-level aggregate, so a {service="…"} SLO on one would resolve
    # Missing → skipped on EVERY run (a gate that silently stops gating). Fail fast in
    # _validate_slo instead. A same-family non-per_pod probe for the service (programmatic
    # Experiments) restores the aggregate, hence the subtraction.
    summed = {
        (d.name, p.labels["service"])
        for p in probes
        if "service" in p.labels and not getattr(p, "_per_pod", False)
        for d in p.describe()
    }
    per_pod_only = {
        (d.name, p.labels["service"])
        for p in probes
        if "service" in p.labels and getattr(p, "_per_pod", False)
        for d in p.describe()
    } - summed
    _validate_slo(slo, registry, declared_facets, declared_services, loads, per_pod_only)

    experiment = Experiment(
        subject=Subject(name=subj_name, target=target, provisioner=provisioner),
        workload=workload,
        resources=resources,
        loads=loads,
        probes=probes,
        derived=derived,
        cases=cases,
        mix=mix,
        facet_order=_parse_facet_order(raw.get("facets")),
        slo=slo,
        abort_on_fail=bool(raw.get("abort_on_fail", False)),
        strict_slo=bool(raw.get("strict_slo", False)),  # skip → run failure (default lenient)
        # experiment name = config `name` (the named experiment dir), default subject slug
        name=str(raw.get("name") or _slug(subj_name)),
        observe_interval_s=float(raw.get("observe_interval_s", 5.0)),
        teardown=bool(raw.get("teardown", False)),
    )
    # `runs_dir` is the parent holding one dir per experiment (output_dir = legacy alias)
    return experiment, raw.get("runs_dir") or raw.get("output_dir") or "./runs"


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s).strip("-") or "perf"


def _parse_cases(raw: dict) -> list[Case]:
    """Top-level ``cases:`` → the canonical Case pool. Backward-compat: no cases but a
    top-level ``payload``/``payload_file`` → one default Case; neither → empty (Engine
    uses one anonymous Case). An entry's ``weight`` is experiment usage, not part of
    the Case — ``_parse_mix`` lifts it into the Experiment's mix Overlay."""
    items = raw.get("cases")
    if items:
        return [
            Case(
                id=str(cc.get("id", f"case{i}")),
                input=_load_input(cc.get("input_file"), cc.get("input")) or {},
                facets={k: str(v) for k, v in (cc.get("facets") or {}).items()},
            )
            for i, cc in enumerate(items)
        ]
    payload = _load_input(raw.get("payload_file"), raw.get("payload"))
    return [Case(id="default", input=payload)] if payload is not None else []


def _parse_mix(raw: dict, cases: list[Case]) -> Overlay:
    """Inline ``cases[].weight`` → an Overlay of load weight per case.id (unwritten → 1.0).

    The Case OBJECT still carries no weight (spec: weight is "how this experiment
    uses the case", not its identity) — but the config entry IS experiment usage,
    so the weight sits right on it instead of a separate top-level key to cross-
    reference. Fail fast: a mix that zeroes every case is an error (the Engine's
    ``random.choices`` needs a positive weight)."""
    if "mix" in raw:
        raise ValueError(
            "top-level `mix:` was removed — put `weight:` on each `cases:` entry "
            "(the entry is experiment usage; the Case itself still carries no weight)"
        )
    weights: dict[str, float] = {}
    for i, cc in enumerate(raw.get("cases") or []):
        if "weight" in cc:
            weights[str(cc.get("id", f"case{i}"))] = float(cc["weight"])
    mix = Overlay(weights)
    eff = mix.resolve([c.id for c in cases], default_of=lambda _: 1.0)
    if eff and not any(w > 0 for w in eff.values()):
        raise ValueError("case weights leave every case at 0 — at least one must be > 0")
    return mix


def _parse_facet_order(facets: dict | None) -> dict[str, list[str]]:
    """Top-level ``facets.<key>.{values, ordered}`` → value order for report sorting."""
    return FacetSchema.from_raw(facets).ordered_value_lists()


def _load_input(file: str | None, inline: dict | None) -> dict | None:
    if inline is not None:
        return inline
    if file:
        import json

        return json.loads(Path(file).expanduser().read_text())
    return None


def _parse_k8s(c: dict | None) -> K8sRef | None:
    if not c:
        return None
    return K8sRef(
        kubeconfig=os.path.expanduser(c["kubeconfig"]),
        namespace=c["namespace"],
        app_label=c["app_label"],
        metrics_prefix=c.get("metrics_prefix", ""),
        metrics_port=int(c.get("metrics_port", 8000)),
        container=c.get("container"),
    )


def _parse_observe(items: list[dict] | None) -> list[Probe]:
    """``observe:`` → the ONE place for per-service resource observation, self +
    downstream in one shape. Each item: ``name`` + ``probes`` + an OPTIONAL ``k8s``
    block; omit ``k8s`` and the entry is the **Subject** (its pod via
    ``subject.provisioner.k8s``, its ``/metrics`` via the Subject base_url). Pod
    probes (top/rss/restart) read a K8sRef; ``metrics`` scrapes the Subject's
    ``/metrics`` (downstream /metrics needs a URL — unsupported, so it's only valid
    on the k8s-less Subject entry). Metrics are service-prefixed (``top.<name>.…``),
    so the report overlays same-unit series across services."""
    out: list[Probe] = []
    for item in items or []:
        service = str(item["name"])
        if "derive" in item:
            raise ValueError(
                f"observe[{service}].derive moved to the TOP-LEVEL `derived:` key — "
                f"ratios are computed at reduce time from counter families "
                f"(`ratio: [metrics.<num>, metrics.<den>]`), not configured per probe"
            )
        ref = _parse_k8s(item.get("k8s"))  # None → the Subject (its pod + base_url)
        # per_pod: top/limits emit one {pod}-labeled series per pod instead of the
        # service-level sum (per-pod usage vs its OWN request/limit on one chart)
        per_pod = bool(item.get("per_pod", False))
        probes = item.get("probes") or ["top"]
        scrape = _parse_scrape(item.get("scrape"), service)
        if scrape and "metrics" not in probes:
            raise ValueError(
                f"observe[{service}].scrape: needs the `metrics` probe on this "
                f"entry (it rides the /metrics scrape)"
            )
        metrics_url = item.get("metrics_url")  # convention: http://<service-ip>:<port>/metrics
        for pname in probes:
            if pname in _K8S_PROBES:
                out.append(_PROBES[pname](k8s=ref, service=service, per_pod=per_pod))
            elif pname == "metrics":
                if ref is not None and not metrics_url:
                    raise ValueError(
                        f"observe[{service}].probes: `metrics` on a downstream entry "
                        f"needs `metrics_url` (the Subject entry defaults to base_url"
                        f" + /metrics)"
                    )
                out.append(
                    MetricsScrapeProbe(
                        service=service,
                        scrape=scrape,
                        url=str(metrics_url) if metrics_url else None,
                        # a downstream entry's starlette prefix comes from ITS k8s ref
                        # (the sample-time fallback reads the Subject's)
                        prefix=ref.metrics_prefix if ref and ref.metrics_prefix else None,
                    )
                )
            else:
                raise ValueError(
                    f"observe[{service}].probes: {pname!r} not allowed — only "
                    f"metrics/top/rss/restart observe a service"
                )
    return out


def _parse_derived(items: list[dict] | None, probes: list[Probe]) -> list[DeriveSpec]:
    """Top-level ``derived:`` → per-trial ratio scalars (``Δnum ÷ Δden`` of two counter
    FAMILIES over the steady window — the Prometheus-histogram mean idiom). ``num``/
    ``den`` are family names (``metrics.sse_ttft_sum``); the Engine joins them per
    label set at reduce time, so a per-service or ``by:``-grouped scrape derives one
    ratio per series automatically. Fail fast on a name that is not a declared
    counter family — a silent no-join would render as 'no data'."""
    counters = {d.name for p in probes for d in p.describe() if d.value_kind == "counter"}
    taken = {d.name for p in probes for d in p.describe()}
    # by-grouping per scraped family — num/den must agree, else the reduce-time label
    # join finds no common label set and the ratio silently reads as 'no data'
    by_of: dict[str, tuple[str, ...]] = {}
    for p in probes:
        for s in getattr(p, "scrape", []):
            by_of[f"{p.family}.{s.name}"] = s.by
    out: list[DeriveSpec] = []
    for d in items or []:
        name = d.get("as")
        if not isinstance(name, str) or not name:
            raise ValueError(f"derived entry needs a string `as`: {d!r}")
        ratio = d.get("ratio")
        if not (isinstance(ratio, list) and len(ratio) == 2):
            raise ValueError(f"derived[{name}]: needs `ratio: [num, den]`, got {ratio!r}")
        num, den = (str(x) for x in ratio)
        for ref_name in (num, den):
            if ref_name not in counters:
                raise ValueError(
                    f"derived[{name}]: {ref_name!r} is not a declared counter family "
                    f"(declared: {sorted(counters) or 'none'})"
                )
        if by_of.get(num, ()) != by_of.get(den, ()):
            raise ValueError(
                f"derived[{name}]: num/den must share the same `by` grouping, got "
                f"{num!r} by={list(by_of.get(num, ()))} vs {den!r} by={list(by_of.get(den, ()))}"
            )
        if name in taken or any(o.name == name for o in out):
            raise ValueError(f"derived: duplicate metric name {name!r}")
        out.append(
            DeriveSpec(
                name=name,
                num=num,
                den=den,
                unit=str(d.get("unit", "")),
                description=str(d.get("description", "")),
            )
        )
    return out


def _parse_scrape(items: list[dict] | None, service: str) -> list[ScrapeSpec]:
    """``observe[].scrape:`` → extra Prometheus families for the ``metrics`` probe.

    Each item: ``from`` (exposition sample name; for a histogram use its ``…_count``
    / ``…_sum`` series) + optional ``as`` (bare metric name, default ``from``),
    ``kind`` (counter|gauge, default counter — an instantaneous scrape can't be a
    distribution), ``unit``, ``description``, ``match`` ({label: value} keep-filter),
    ``drop`` ({label: [values]} discard-filter) and ``by`` (label name or list —
    keep one series per distinct label value, PromQL's ``sum by``; mind the
    cardinality, see ``ScrapeSpec``)."""
    out: list[ScrapeSpec] = []
    # builtin bare names + the synthesized health series — a scrape may not shadow
    seen = {"req_total", "in_progress", "up"}
    for s in items or []:
        source = s.get("from")
        if not isinstance(source, str) or not source:
            raise ValueError(f"observe[{service}].scrape entry needs a string `from`: {s!r}")
        name = str(s.get("as") or source)
        kind = str(s.get("kind", "counter"))
        if kind not in ("counter", "gauge"):
            raise ValueError(
                f"observe[{service}].scrape[{name}]: kind must be counter|gauge, got {kind!r}"
            )
        if name in seen:
            raise ValueError(f"observe[{service}].scrape: duplicate/builtin metric name {name!r}")
        seen.add(name)
        by_raw = s.get("by")
        if isinstance(by_raw, str):
            by_raw = [by_raw]
        if by_raw is not None and not (
            isinstance(by_raw, list) and by_raw and all(isinstance(x, str) and x for x in by_raw)
        ):
            raise ValueError(
                f"observe[{service}].scrape[{name}]: `by` must be a label name or a "
                f"non-empty list of label names, got {s.get('by')!r}"
            )
        out.append(
            ScrapeSpec(
                source=source,
                name=name,
                value_kind=kind,  # type: ignore[arg-type]
                unit=str(s.get("unit", "count")),
                description=str(s.get("description", "")),
                match={str(k): str(v) for k, v in (s.get("match") or {}).items()},
                drop={
                    str(k): tuple(str(x) for x in vals) for k, vals in (s.get("drop") or {}).items()
                },
                by=tuple(by_raw or ()),
            )
        )
    return out


def _parse_provisioner(c: dict | None, k8s: K8sRef | None) -> Provisioner | None:
    """``subject.provisioner:`` → a Provisioner, or None (the common case: the
    service is already deployed; ``resources:`` entries merely label the trials)."""
    if not c:
        return None
    kind = c.get("type", "helm")
    if kind == "helm":
        if k8s is None:
            raise ValueError("a helm provisioner requires `subject.k8s` (kubeconfig/namespace)")
        return HelmProvisioner(
            release=c["release"],
            chart_path=os.path.expanduser(c["chart_path"]),
            namespace=k8s.namespace,
            kubeconfig=k8s.kubeconfig,
            base_values=_expand(c.get("base_values")),
            set_paths=c.get("set_paths"),
            rollout_timeout_s=int(c.get("rollout_timeout_s", 180)),
            extra_set=c.get("extra_set"),
        )
    raise ValueError(f"unknown provisioner type: {kind!r} (only `helm`)")


def _parse_resources(c: dict) -> ResourceProfile:
    return ResourceProfile(
        cpu=c.get("cpu"),
        memory=c.get("memory"),
        workers=c.get("workers"),
        replicas=int(c.get("replicas", 1)),
        extra={k: str(v) for k, v in (c.get("extra") or {}).items()},
    )


def _parse_loads(c: dict) -> list[LoadProfile]:
    """``load:`` block → the Experiment's Load arms.

    Two ways to express the schedule, mutually exclusive:
      - ``stages:`` → one arm with an explicit shape (a step/spike curve).
      - ``levels:``/``level:`` (+ ``ramp_s``/``steady_s``) → one ramp→hold arm
        per level, the common capacity sweep. Here ``warmup_s`` defaults to the
        ramp window (the ramp is the warmup).
    Common across both: ``model`` (open/closed), ``pacing`` (closed), and
    ``max_inflight`` (open).
    """
    model = c.get("model", "closed")
    if model not in _LOAD_MODELS:
        raise ValueError(f"load.model must be one of {_LOAD_MODELS}, got {model!r}")
    if c.get("stages") and ("levels" in c or "level" in c):
        raise ValueError("load: set either `stages` or `levels`/`level`, not both")
    pacing = _parse_pacing(c.get("pacing"))
    max_inflight = c.get("max_inflight")
    # mid-trial circuit breaker (open + closed): stop the arm early once the cumulative
    # error rate crosses this fraction — distinct from the between-trial abort_on_fail SLO
    aoer = c.get("abort_on_error_rate")
    abort_on_error_rate = float(aoer) if aoer is not None else None
    breaker_min_n = int(c.get("breaker_min_n", 20))
    graceful_stop_s = float(c.get("graceful_stop_s", 30.0))  # drain window before cancel
    # fail-fast on a nonsensical stop policy (a misconfigured breaker is worse than none:
    # 0 trips healthy traffic, >1 never trips, min_n<1 has no statistical floor)
    if abort_on_error_rate is not None and not 0 < abort_on_error_rate <= 1:
        raise ValueError(f"load.abort_on_error_rate must be in (0, 1]; got {abort_on_error_rate}")
    if breaker_min_n < 1:
        raise ValueError(f"load.breaker_min_n must be >= 1; got {breaker_min_n}")
    if graceful_stop_s < 0:
        raise ValueError(
            f"load.graceful_stop_s must be >= 0 (0 = hard stop); got {graceful_stop_s}"
        )

    if c.get("stages"):
        schedule = _parse_schedule(c["stages"], float(c.get("start_level", 0.0)))
        return [
            LoadProfile(
                model=model,
                schedule=schedule,
                pacing=pacing,
                warmup_s=float(c.get("warmup_s", 0.0)),
                max_inflight=max_inflight,
                abort_on_error_rate=abort_on_error_rate,
                breaker_min_n=breaker_min_n,
                graceful_stop_s=graceful_stop_s,
            )
        ]

    levels = c.get("levels") or [c.get("level", 10)]
    ramp_s = float(c.get("ramp_s", 20.0))
    steady_s = float(c.get("steady_s", 120.0))
    warmup_s = float(c.get("warmup_s", ramp_s))
    return [
        LoadProfile(
            model=model,
            schedule=Schedule.ramp_hold(float(lv), ramp_s, steady_s),
            pacing=pacing,
            warmup_s=warmup_s,
            max_inflight=max_inflight,
            abort_on_error_rate=abort_on_error_rate,
            breaker_min_n=breaker_min_n,
            graceful_stop_s=graceful_stop_s,
        )
        for lv in levels
    ]


def _parse_pacing(p: dict | None) -> Pacing:
    if not p:
        return Pacing()
    kind = p.get("kind", "none")
    if kind not in _PACING_KINDS:
        raise ValueError(f"load.pacing.kind must be one of {_PACING_KINDS}, got {kind!r}")
    return Pacing(
        kind=kind,
        secs=float(p.get("secs", 0.0)),
        max_secs=float(p.get("max_secs", 0.0)),
    )


def _parse_schedule(stages: list[dict], start_level: float) -> Schedule:
    """``stages:`` list → Schedule. Each item is ``{ramp_to, over_s}`` or
    ``{hold, for_s}``."""
    out: list[Stage] = []
    for s in stages:
        name = s.get("name")
        if "ramp_to" in s:
            out.append(
                Stage(
                    over_s=float(s["over_s"]), to_level=float(s["ramp_to"]), kind="ramp", name=name
                )
            )
        elif "hold" in s:
            out.append(
                Stage(over_s=float(s["for_s"]), to_level=float(s["hold"]), kind="hold", name=name)
            )
        else:
            raise ValueError(f"stage needs `ramp_to`+`over_s` or `hold`+`for_s`: {s!r}")
    return Schedule(stages=tuple(out), start_level=start_level)


def _parse_slo(items: list[dict] | None) -> list[SloAssertion]:
    """``slo:`` list → SloAssertions. Each item: ``metric`` (carries any facet/stage/
    service label, e.g. ``duration_ms{difficulty="simple"}.p99``) + exactly one op key
    (``lt``/``lte``/``gt``/``gte``/``between``) + optional ``level``. Syntax only here;
    metric/label existence is checked in ``_validate_slo``."""
    out: list[SloAssertion] = []
    for s in items or []:
        metric = s.get("metric")
        if not isinstance(metric, str) or not metric:
            raise ValueError(f"slo entry needs a string `metric`: {s!r}")
        if "scope" in s:
            raise ValueError(
                "slo.scope was removed — put the slice in the metric as a label: "
                "facet:difficulty=simple → 'duration_ms{difficulty=\"simple\"}.p99', "
                "stage:hold@40 → '...{stage=\"hold@40\"}...'"
            )
        ops = [k for k in _SLO_OPS if k in s]
        if len(ops) != 1:
            raise ValueError(f"slo entry needs exactly one of {list(_SLO_OPS)}: {s!r}")
        op = ops[0]
        threshold = tuple(float(x) for x in s[op]) if op == "between" else float(s[op])
        level = s.get("level")
        out.append(
            SloAssertion(
                metric=metric,
                op=op,
                threshold=threshold,
                level=float(level) if level is not None else None,
            )
        )
    return out


def _validate_producers(probes: list[Probe], workload: Workload) -> None:
    """Fail-fast (config time) on a producer that declares a metric family wrongly:
    a Workload may only declare ``request``-side distributions; a Probe only
    ``resource``-side families; no producer may shadow a builtin ``request.*`` family;
    and a family re-declared by two producers must agree on its metadata. Keeps the
    side → who-produces-it invariant honest (the report/SLO trust ``describe()``)."""
    builtin_request = {d.name for d in REQUEST_DESCRIPTORS}
    seen: dict[str, MetricFamily] = {}

    def _claim(fam: MetricFamily, who: str) -> None:
        if fam.name in builtin_request:
            raise ValueError(f"{who} may not declare the builtin request metric {fam.name!r}")
        prev = seen.get(fam.name)
        if prev is not None and prev != fam:
            raise ValueError(
                f"metric family {fam.name!r} declared with conflicting metadata: {prev} vs {fam}"
            )
        seen[fam.name] = fam

    for m in workload.describe():
        if m.side != "request" or m.value_kind != "distribution":
            raise ValueError(
                f"Workload.describe() may only declare request-side distributions; got "
                f"side={m.side!r} value_kind={m.value_kind!r} for {m.name!r}"
            )
        _claim(m, "Workload.describe()")
    for p in probes:
        for d in p.describe():
            if d.side != "resource":
                raise ValueError(
                    f"Probe {type(p).__name__}.describe() may only declare resource-side "
                    f"metrics; got side={d.side!r} for {d.name!r}"
                )
            _claim(d, f"Probe {type(p).__name__}.describe()")


def _static_registry(
    probes: list[Probe], workload: Workload, derived: list[DeriveSpec]
) -> dict[str, MetricFamily]:
    """Statically-knowable metric FAMILIES for SLO validation: builtin ``request.*`` +
    each Probe's ``describe()`` + top-level ``derived:`` ratios + the Workload's declared
    per-request metrics. Keyed by family name (labels are slice selectors, not identity),
    so unit/value_kind/description is stored once per family — not duplicated per
    service. (Dynamic, undeclared per-request metrics aren't here — discovered only at
    run time, so a dotted ref to one is allowed and skip-checked.)"""
    reg: dict[str, MetricFamily] = {
        d.name: d for d in (*REQUEST_DESCRIPTORS, *PER_REQUEST_DESCRIPTORS)
    }
    for p in probes:
        reg.update({d.name: d for d in p.describe()})  # by family (dedup across services)
        # the Engine synthesizes `<family>.up` health series per probe (Prometheus `up`
        # analogue) — declare them so e.g. `metrics.up{service="…"}.mean` can gate
        reg[f"{p.family}.up"] = MetricFamily(
            name=f"{p.family}.up",
            unit="",
            side="resource",
            value_kind="gauge",
            source=p.source,
            description="probe health (1 ok / 0 failed) — mean 即观测可用率",
        )
    for spec in derived:  # derived ratio scalars are declared too → SLO-addressable
        reg[spec.name] = MetricFamily(
            name=spec.name,
            unit=spec.unit,
            side="resource",
            value_kind="scalar",
            source="http",
            description=spec.description,
        )
    reg.update({d.name: d for d in workload.describe()})
    return reg


def _declared_facet_pairs(facets: dict | None, cases: list[Case], workload: Workload) -> set[str]:
    """``k=v`` facet pairs an SLO scope may gate: the static Case mix + the
    Workload's declared runtime facets + any ``facets:`` block values."""
    pairs = {f"{k}={v}" for c in cases for k, v in c.facets.items()}
    for fd in workload.describe_facets():
        pairs.update(f"{fd.name}={v}" for v in fd.values)
    for key, spec in (facets or {}).items():
        if isinstance(spec, dict):
            pairs.update(f"{key}={v}" for v in spec.get("values", []))
    return pairs


def _validate_slo(
    slo: list[SloAssertion],
    registry: dict[str, MetricFamily],
    declared_facets: set[str],
    declared_services: set[str],
    loads: list[LoadProfile],
    per_pod_only: set[tuple[str, str]] = frozenset(),  # (family, service) with no aggregate
) -> None:
    """Fail fast on a misconfigured gate (a perf gate must not silently skip).

    One rule per ``side`` (the family declares it; no name-pattern special cases):
      - resource side — selected by a ``{service=…}`` label: explicit legal stat,
        observed service, no facet/stage co-labels, and the service must have an
        aggregate series (a ``per_pod``-only family would skip every run).
      - request side — facet/stage labels select a slice: at most ONE (the report is
        a marginal pivot, not a cube) and its value must be one a run produces.
    ``value_kind`` gates the stat either way (``validate_ref``)."""
    stage_labels = {
        lbl for ld in loads if ld.schedule.is_multi_stage for lbl in ld.schedule.stage_durations()
    }
    for a in slo:
        name, labels, stat = parse_ref(a.metric)
        fam = registry.get(name)
        slice_labels = {k: v for k, v in labels.items() if k != "service"}  # facet / stage
        if len(slice_labels) > 1:
            raise ValueError(
                f"slo.metric {a.metric!r}: at most one facet/stage slice label "
                f"(report is a marginal pivot, not a cube); got {sorted(slice_labels)}"
            )

        if "service" in labels:
            # a `service` label selects a resource-side series — pin it down hard, or
            # ``request.duration_ms{service="chat"}.p99`` would pass config then
            # silently go missing on every run.
            if stat is None:
                raise ValueError(
                    f"slo.metric {a.metric!r}: a `service`-labeled metric needs an explicit "
                    f"stat ('<name>{{service=\"…\"}}.<stat>') — a resource series, not an alias"
                )
            if fam is None:
                raise ValueError(f"slo.metric {a.metric!r}: {name!r} is not a declared metric")
            if fam.side != "resource":
                raise ValueError(
                    f"slo.metric {a.metric!r}: a `service` label is only valid on a "
                    f"resource-side metric; {name!r} is request-side"
                )
            if slice_labels:
                raise ValueError(
                    f"slo.metric {a.metric!r}: a resource metric can't also carry a facet/stage "
                    f"label {sorted(slice_labels)}"
                )
            validate_ref(a.metric, registry)  # stat legal for the family's value_kind
            if labels["service"] not in declared_services:
                raise ValueError(
                    f"slo.metric {a.metric!r}: service {labels['service']!r} not observed "
                    f"(observe: {sorted(declared_services) or 'none'})"
                )
            if (name, labels["service"]) in per_pod_only:
                raise ValueError(
                    f"slo.metric {a.metric!r}: service {labels['service']!r} is observed "
                    f"per_pod — only {{pod,service}} series exist (no service-level "
                    f"aggregate), so this gate would skip every run; drop per_pod for "
                    f"that service or remove this SLO"
                )
            continue

        # request side (no service label): a builtin alias, or a declared family + legal stat
        if stat is None:
            if name not in SLO_METRICS:
                raise ValueError(
                    f"slo.metric {a.metric!r}: {name!r} is not a builtin field "
                    f"{sorted(SLO_METRICS)} (for a probe/per-request metric use '<name>.<stat>')"
                )
        elif fam is not None:
            validate_ref(a.metric, registry)  # stat legal for the family's value_kind
            if fam.side == "resource" and slice_labels:
                raise ValueError(
                    f"slo.metric {name!r} is a resource-side metric — trial-global, "
                    f"can't be sliced by {sorted(slice_labels)}"
                )
        else:
            # an SLO gate must fail-fast, not silently skip a typo → the metric must be
            # DECLARED (builtin / probe / framework ttft_ms / Workload.describe()).
            # A dynamic per-request metric still reaches the report/CSV — just can't gate.
            raise ValueError(
                f"slo.metric {a.metric!r}: {name!r} is not a declared metric — only declared "
                "metrics can gate (declare a per-request metric via Workload.describe(); a "
                "dynamic first_<event>_ms reaches the report but can't gate)"
            )

        # the facet/stage label value must be one a run actually produces
        for k, v in slice_labels.items():
            if k == "stage":
                if v not in stage_labels:
                    raise ValueError(
                        f"slo.metric {a.metric!r}: stage {v!r} unknown "
                        f"(multi-stage schedules expose: {sorted(stage_labels) or 'none'})"
                    )
            elif f"{k}={v}" not in declared_facets:
                raise ValueError(
                    f"slo.metric {a.metric!r}: facet {k}={v} unknown "
                    f"(declared: {sorted(declared_facets) or 'none'})"
                )


def _expand(p: str | None) -> str | None:
    return os.path.expanduser(p) if p else None
