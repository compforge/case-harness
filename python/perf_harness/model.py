"""perf_harness value objects — the ubiquitous language, as plain data.

The whole harness is three lines::

    一个 Experiment = ResourceProfile(资源档) × LoadProfile(负载档) 的网格;
    每个格子(Trial)由 Workload 发带 facet 的 Case、Probe 周期采样, 产出一张 metric 表;
    report / SLO / analyze 都是对这张表的查询。

This module holds the nouns that are *just data* (no behaviour): the
time-series primitives (`Sample`/`Series`), one request's `Outcome` + its
`Verdict`, the `ResourceProfile` (资源档) + reachability (`Target`/`K8sRef`),
and the per-Trial/-Run aggregates (`RequestStats`/`TrialResult`/`Run`). The load
*shape* vocabulary (`LoadProfile`/`Schedule`/`Pacing`) lives in `load.py`;
behaviour (firing load, sampling probes, provisioning) lives in sibling modules.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from perf_harness.metric import Caveat, MetricFamily, MetricSummary

if TYPE_CHECKING:
    # annotation-only: importing drive at runtime would cycle (drive.workload
    # constructs this module's Outcome/Verdict)
    from perf_harness.drive.load import LoadProfile


def make_run_id() -> str:
    """A sortable run id: ``YYYYMMDD-HHMMSS`` (local time). One run = one config run."""
    return time.strftime("%Y%m%d-%H%M%S")


@dataclass(frozen=True)
class Sample:
    """One reading of one Metric at time ``t`` (monotonic seconds into the Trial)."""

    t: float
    value: float


@dataclass
class Series:
    """A named Metric's readings over a Trial — one time-varying signal."""

    metric: str
    unit: str
    samples: list[Sample] = field(default_factory=list)


@dataclass
class Outcome:
    """Client-side result of one Workload.fire() — the request-side truth.

    Two-stage contract: ``fire`` records the *raw observation* (status, timing,
    SSE frame/byte counts, and protocol-specific signals in ``meta``); the
    *verdict* (``ok`` / ``error_kind``) is then decided by ``Workload.judge`` —
    NOT by ``fire`` — and written back by the Engine. So ``fire`` may leave
    ``ok``/``error_kind`` at their defaults; the authoritative values come from
    judge. Keeping judge a pure function of this raw Outcome means verdicts can
    be recomputed offline from stored Outcomes without re-firing.

    Latency percentiles, throughput and the error taxonomy are aggregated from
    these (not from a server histogram), so they are always available even when
    the Subject exposes no /metrics.
    """

    status: int | None
    duration_ms: float
    ok: bool = False  # verdict — set by Workload.judge() via the Engine, not by fire()
    error_kind: str | None = None  # verdict bucket — set by judge(): "ReadTimeout" / "503" / …
    events: int = 0  # SSE frames consumed (0 for non-SSE)
    nbytes: int = 0
    metrics: dict[str, float] = field(
        default_factory=dict
    )  # per_request metric values fire() measured: ttft_ms / first_<event>_ms … (→ MetricStat)
    dropped: bool = False  # never-sent (open-loop max_inflight shed); NOT a latency sample
    stage: str | None = None  # active schedule stage label (only stamped for multi-stage runs)
    meta: dict = field(
        default_factory=dict
    )  # raw signals fire() records for judge(): exc / saw_done / error_frames / ttft_ms …
    facets: dict[str, str] = field(
        default_factory=dict
    )  # fired Case's dims; report pivots by these
    case_id: str = ""  # canonical Case.id stamped by the scheduler for cross-run joins


@dataclass(frozen=True)
class Verdict:
    """The judgement on one Outcome — ``Workload.judge``'s return.

    ``error_kind`` is the report's error bucket; ``None`` iff ``ok``.
    """

    ok: bool
    error_kind: str | None = None


# The unit of load `Case` now lives in `common.case` — the canonical, harness-neutral case
# reused by e2e / eval / perf (perf reads it directly; see config.py / engine.py). Its
# per-experiment load weight is NOT a Case field: weight is "how this run uses the case",
# not the case's identity — config entries carry an inline `weight:` that the loader
# lifts into the `Experiment.mix` Overlay (keyed by case.id).


# ---------------------------------------------------------------------------
# ResourceProfile (资源档) + Subject reachability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class K8sRef:
    """Coordinates a K8s-family Source needs to observe the Subject's pod.

    Optional on a Target: when absent, K8s probes are skipped (e.g. a Subject
    at a non-cluster endpoint).
    """

    kubeconfig: str
    namespace: str
    app_label: str  # e.g. "app.kubernetes.io/name=example"
    metrics_prefix: str = ""  # starlette_exporter prefix, e.g. "chat"
    metrics_port: int = 8000
    container: str | None = None


@dataclass(frozen=True)
class ResourceProfile:
    """资源档: the resource budget the Subject runs under for one Trial.

    Substrate-agnostic data — it does not care whether a HelmProvisioner drove it,
    a DockerProvisioner did, or a human set it and the harness merely *records* it
    (no provisioner). ``extra`` carries arbitrary ``helm --set`` style overrides.
    """

    cpu: str | None = None  # "2" / "500m"
    memory: str | None = None  # "2Gi"
    workers: int | None = None  # uvicorn workers
    replicas: int = 1
    extra: dict[str, str] = field(default_factory=dict)

    def label(self) -> str:
        """Short key for report rows, e.g. ``w2/2Gi``."""
        parts = []
        if self.workers is not None:
            parts.append(f"w{self.workers}")
        if self.memory:
            parts.append(self.memory)
        if self.cpu:
            parts.append(f"cpu{self.cpu}")
        return "/".join(parts) or "default"


@dataclass(frozen=True)
class Target:
    """The Subject's reachability — substrate-agnostic. ``k8s`` enables K8s probes."""

    base_url: str
    headers: dict[str, str] = field(default_factory=dict)
    k8s: K8sRef | None = None


# ---------------------------------------------------------------------------
# Per-Trial aggregate — one row of the summary table
# ---------------------------------------------------------------------------


@dataclass
class RequestStats:
    """Request-side aggregate over a set of Outcomes — a whole Trial, or one facet slice.

    ``n`` / latency / throughput / error_rate cover only *sent* requests. Open-loop
    ``client_saturated`` drops (never-sent shed load) are NOT latency samples and
    are excluded from those — they live in ``n_dropped`` instead, with
    ``drop_rate`` = dropped / (sent + dropped). A non-trivial ``drop_rate`` means
    the generator measured below its intended offered load, so the latency
    percentiles understate reality (coordinated omission) and the Trial's latency
    is not trustworthy — the report flags it.
    """

    n: int
    n_ok: int
    throughput_rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    error_breakdown: dict[str, int]
    n_dropped: int = 0
    mean_ms: float = 0.0  # mean request latency (feeds the request.duration_ms distribution)
    metrics: dict[str, MetricSummary] = field(
        default_factory=dict
    )  # per_request metric distributions for this slice (ttft_ms / first_<event>_ms …)
    caveats: frozenset[Caveat] = field(default_factory=frozenset)
    """Slice-level trustworthiness, minted at REDUCE — ``co_biased`` (closed-loop
    tail), ``high_drop`` (open-loop saturation), ``few_samples``. Stamped onto this
    slice's ``request.duration_ms`` distribution so a CO-biased p99 can't be read as
    clean; the report renders them as flags instead of prose."""

    @property
    def drop_rate(self) -> float:
        total = self.n + self.n_dropped
        return self.n_dropped / total if total else 0.0


# ---------------------------------------------------------------------------
# Stop model — how a trial ended (every trial ends with one, "deadline" is normal)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StopSnapshot:
    """The watcher's view at the instant a breaker tripped — NOT the post-warmup
    ``overall``. Captured from the breaker's own (cumulative, incl-warmup) window so
    the report can answer 'why did it stop' from the trip itself, not by reverse-
    engineering ``overall``. ``None`` on a clean ``deadline`` stop."""

    at_s: float  # seconds into the trial when it tripped
    sent: int  # requests sent at trip (the breaker's denominator)
    errors: int  # judged failures at trip (the breaker's numerator)
    error_rate: float  # errors / sent at trip
    threshold: float  # the configured abort_on_error_rate it crossed


@dataclass(frozen=True)
class TrialStop:
    """How one trial ended. EVERY trial has one — ``reason="deadline"`` is the normal
    end (planned ``steady_s`` reached), other reasons mean it stopped early. The
    enact census records what was in flight when the load wound down: a cancelled
    in-flight request is ``interrupted`` (NOT a latency sample / error — see
    ``RequestStats``), counted here only.

    Reasons today: ``deadline`` (normal) · ``error_rate`` (circuit breaker). External
    / resource / per-stage stops will add reasons without changing the shape."""

    reason: str = "deadline"
    snapshot: StopSnapshot | None = None  # the trip view; None for a deadline stop
    inflight_at_stop: int = 0  # requests in flight when the wind-down began
    interrupted: int = 0  # in-flight requests force-cancelled (drain window exceeded)
    force_cancelled: bool = False  # True iff in-flight REQUESTS had to be cut (interrupted > 0)

    @property
    def early(self) -> bool:
        """The trial stopped before its planned window (anything but a deadline end)."""
        return self.reason != "deadline"


@dataclass(frozen=True)
class ProbeErrors:
    """One probe's observation-failure census for a trial — observability health is
    DATA (a probe that silently fails paints a fake-flat trend). ``failures`` of
    ``ticks`` sampling rounds raised; ``last`` is the most recent error (repr).
    Observational only: it flags summaries (``probe_error`` caveat) and the report,
    never the run verdict."""

    failures: int
    ticks: int
    last: str


@dataclass
class TrialResult:
    """Collapsed result of one (subject × resources × load) grid point.

    ``overall`` aggregates every Outcome. ``by_facet`` is the marginal pivot:
    for each facet key present, value → its own RequestStats (other facets
    marginalized), so the report can slice by whichever axis you're investigating
    (difficulty today, kb tomorrow) without re-running. ``probe_metrics``/
    ``series`` are the resource-side (per Probe).

    ``by_stage`` is populated only for multi-stage schedules (spike/step): label →
    stats for each schedule stage, so a stepped run yields a per-level capacity
    curve in one trial. For those runs ``overall`` is a post-warmup average ACROSS
    stages (mixed load levels) — read ``by_stage`` hold@ buckets for capacity.
    """

    subject: str
    resources: ResourceProfile
    load: LoadProfile
    overall: RequestStats
    by_facet: dict[str, dict[str, RequestStats]]
    series: dict[str, Series]
    by_stage: dict[str, RequestStats] = field(default_factory=dict)
    stop: TrialStop = field(default_factory=TrialStop)
    """How this trial ended (every trial has one; default ``reason="deadline"`` =
    normal). When it stopped early (e.g. the error-rate breaker), the trial's numbers
    are *partial* — throughput especially understates (denominator is the planned
    window) — so the report flags it from ``stop.reason``/``stop.snapshot`` and reads
    'it broke at this load', not a clean capacity point. Replaces the old ``aborted``
    bool with a structured, explainable stop."""
    slo: list[SloCheck] = field(default_factory=list)  # per-run SLO gate, evaluated on this trial
    probe_metrics: dict[str, MetricSummary] = field(default_factory=dict)
    """Trial-global ``time_sampled`` metric summaries (gauge/counter), keyed by
    metric name (``top.mem_mi`` / ``metrics.req_total`` / ``client.inflight``).
    Resource metrics are NOT per-facet/-stage sliceable — they only live here, at
    the trial level (see metric-model.md §3.2)."""
    metrics: dict[str, MetricFamily] = field(default_factory=dict)
    """Unified metric registry: every report-visible metric FAMILY name → its
    family descriptor (no labels — metadata declared once), spanning all kinds:
    ``per_request`` (slice ``RequestStats.metrics``), ``time_sampled``
    (``probe_metrics``) and ``derived`` (builtin ``request.*``). report/SLO read
    value_kind/source/unit from here and address any series as ``<name>{labels}.<stat>``
    regardless of which pipeline produced it. The MetricStore wraps these trials to
    serve those reads."""
    outcomes: list[tuple[float, Outcome]] = field(default_factory=list, repr=False)
    """Raw request-side facts: every ``(t, Outcome)`` the drivers recorded, incl.
    warmup and drops — the request analogue of ``series`` (the time_sampled raw).
    Summaries above are derived from these at reduce time; they are kept so the
    persistence layer (``runio``) can write the raw layer (``outcomes.jsonl``) and
    offline analysis can re-slice / recompute without re-firing."""
    probe_errors: dict[str, ProbeErrors] = field(default_factory=dict)
    """Probes that FAILED at least one sampling tick this trial (key = unique probe
    name, e.g. ``metrics.chat``). Their summaries carry the ``probe_error`` caveat,
    absent reads resolve to ``Missing("probe_error")`` (≠ "slice没数据"), and the
    validity lens flags them — so a broken /metrics never renders as a calm line."""
    cooldown_start_s: float | None = None
    """Start of the cooldown window in the raw Probe timeline.

    Set after ``Workload.deactivate()`` returns. ``None`` means this trial had no
    cooldown window.
    """

    def label(self) -> str:
        """Stable trial id within a run, e.g. ``w2/2Gi|closed/8c`` — keys the raw
        artifacts (timeseries.csv / outcomes.jsonl rows) back to this trial."""
        return f"{self.resources.label()}|{self.load.label()}"

    @property
    def aborted(self) -> bool:
        """Did this trial stop early (breaker/external), vs run to its deadline?
        Convenience over ``stop.early``; the structured truth is ``self.stop``."""
        return self.stop.early

    @property
    def slo_passed(self) -> bool:
        """Every SLO check on this trial definitively PASSED (vacuously true if none).

        A ``skipped`` check (slice absent) is **not** a pass — so a level with an
        unverifiable SLO does not count as confirmed capacity. The run-level exit
        code is computed separately (lenient on skip unless ``strict_slo``)."""
        return all(c.passed for c in self.slo)


# ---------------------------------------------------------------------------
# SLO — the per-run gate (aggregate verdict, distinct from per-request judge)
# ---------------------------------------------------------------------------

SloOp = Literal["lt", "lte", "gt", "gte", "between"]
SloWindow = Literal["measurement", "cooldown"]


@dataclass(frozen=True)
class SloAssertion:
    """One declarative SLO: resolve ``metric`` on a trial and compare via ``op`` to
    ``threshold``. ``level`` restricts which trials this gates (peak_level == level);
    ``None`` gates every trial.

    The slice is selected by the metric's **labels** (no separate ``scope``): bare
    ``p99_ms`` is overall; ``duration_ms{difficulty="simple"}.p99`` a facet slice;
    ``duration_ms{stage="hold@40"}.p99`` a stage; ``top.cpu_m{service="worker"}.peak``
    a service. ``threshold`` is a float for lt/lte/gt/gte, a ``(lo, hi)`` for between.
    ``window="cooldown"`` re-reduces a resource gauge/counter after ``deactivate``;
    the default ``measurement`` reads the normal load-window summary.
    """

    metric: str
    op: SloOp
    threshold: float | tuple[float, float]
    level: float | None = None
    window: SloWindow = "measurement"


SloState = Literal["pass", "fail", "skipped"]


@dataclass(frozen=True)
class SloCheck:
    """Result of one SloAssertion on one trial — a THREE-state verdict.

    ``skipped`` (``observed is None``) means the metric's slice had no value on this
    trial: a declared facet value no request carried, or a probe that returned no
    data. The check could NOT be evaluated — and a skip is **not** a pass. It never
    lets a trial count as confirmed capacity, and under ``strict_slo`` it fails the
    run; by default it leaves the run's exit code alone but is surfaced as skipped,
    never silently read as green (Prometheus alerts may no-fire on empty; a CI gate
    must not)."""

    assertion: SloAssertion
    observed: float | None
    state: SloState

    @property
    def passed(self) -> bool:
        return self.state == "pass"

    @property
    def skipped(self) -> bool:
        return self.state == "skipped"

    @property
    def failed(self) -> bool:
        return self.state == "fail"


@dataclass
class Run:
    """One execution of an Experiment — its identity plus the per-Trial results.

    ``Engine.run()`` returns this; ``write_run`` lays it out under
    ``runs/<experiment>/<run_id>/`` and serialises it to ``run.json``. ``trials``
    are the cells of the Constraint × Load sweep (the experiment's arms).
    ``passed`` is the run-level SLO gate (all gated trials met their SLOs) — the
    CLI maps it to the process exit code for CI.
    """

    run_id: str
    experiment: str
    created_at: str  # ISO local time the run started
    subject: str
    trials: list[TrialResult]
    passed: bool = True
