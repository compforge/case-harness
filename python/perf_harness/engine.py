"""Engine — pure orchestration: sweep the resources × load grid, one Trial per cell.

One Trial: apply the ResourceProfile (via the Subject's provisioner, if any) →
open a client → drive the load (``drive.scheduler``) while the observer samples
every Probe (``observe.observe_loop``) → collapse outcomes + series into a
TrialResult (``_aggregate``, minting via ``metric.reduce``). The grid is swept
resources-outer so each profile is provisioned once and all load levels run
under it. Execution detail lives in the packages; this module only wires phases.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace

import httpx
from harness_common.overlay import Overlay
from spec_case.model import Case

from perf_harness.drive.load import LoadProfile
from perf_harness.drive.scheduler import drive_closed, drive_open
from perf_harness.drive.workload import TrialContext, Workload
from perf_harness.metric import (
    MetricFamily,
    MetricSummary,
    series_id,
    split_series,
)
from perf_harness.metric.reduce import request_stats, unit_of
from perf_harness.metric.store import PER_REQUEST_DESCRIPTORS, REQUEST_DESCRIPTORS
from perf_harness.model import (
    Outcome,
    ProbeErrors,
    RequestStats,
    ResourceProfile,
    Run,
    Sample,
    Series,
    SloAssertion,
    Target,
    TrialResult,
    make_run_id,
)
from perf_harness.observe import (
    ClientStats,
    Probe,
    ProbeContext,
    ProbeStore,
    observe_loop,
)
from perf_harness.slo import evaluate_slo
from perf_harness.subject import Subject


@dataclass
class Experiment:
    """A named, reproducible perf study — one config = one Experiment.

    Its arms are the resources × load sweep. ``cases`` is the pool the Engine picks
    from each fire (the *what*); the pick is weighted by ``mix`` (the experiment
    workload mix), NOT by the case — the same case is reusable across experiments at
    different weights. Empty pool → one anonymous Case. ``facet_order`` gives ordered
    facets their report sort order.
    """

    subject: Subject
    workload: Workload
    resources: list[ResourceProfile]
    loads: list[LoadProfile]
    probes: list[Probe] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)
    # experiment workload mix: load weight per case.id (unwritten → 1.0; unknown id → error).
    # An Overlay, not a Case field — weight is "how this run uses the case", not its identity.
    mix: Overlay = field(default_factory=Overlay)
    facet_order: dict[str, list[str]] = field(default_factory=dict)
    slo: list[SloAssertion] = field(default_factory=list)  # per-run gate (aggregate verdict)
    abort_on_fail: bool = False  # stop the sweep at the first SLO-failing trial
    strict_slo: bool = False  # treat a skipped SLO (no data) as a run failure, not a pass
    name: str = "perf"  # experiment name → runs/<name>/<run_id>/
    observe_interval_s: float = 5.0
    cooldown_s: float = 0.0  # keep probes running after deactivation for scale-down curves
    teardown: bool = False


class Engine:
    """Runs one Experiment → a Run (run_id + one TrialResult per resources × load)."""

    def __init__(self, experiment: Experiment, *, run_id: str | None = None) -> None:
        self.experiment = experiment
        self.run_id = run_id or make_run_id()  # threaded to Workload.fire + the run dir
        # empty pool → one anonymous Case; weights come from the experiment mix (Overlay
        # keyed by case.id, default 1.0), not from the case — see Experiment.mix.
        self._cases = experiment.cases or [Case(id="default", input={})]
        _mix = experiment.mix.resolve((c.id for c in self._cases), default_of=lambda _: 1.0)
        self._weights = [max(_mix[c.id], 0.0) for c in self._cases]

    async def run(self) -> Run:
        exp = self.experiment
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        trials: list[TrialResult] = []
        passed = True
        aborted = False
        try:
            for profile in exp.resources:
                if exp.subject.provisioner is not None:
                    await exp.subject.provisioner.apply(profile)
                for load in exp.loads:
                    trial = await self._run_trial(exp.subject.target, profile, load)
                    failed = False
                    if exp.slo:
                        trial.slo = evaluate_slo(trial, exp.slo)
                        # the run gate is lenient on skip by default: a skipped check
                        # (slice absent) is surfaced but doesn't flip the exit code;
                        # strict_slo treats an unverifiable SLO as a failure.
                        failed = any(c.failed for c in trial.slo) or any(
                            c.skipped and (exp.strict_slo or c.assertion.window == "cooldown")
                            for c in trial.slo
                        )
                        passed = passed and not failed
                    trials.append(trial)
                    if exp.abort_on_fail and failed:
                        aborted = True  # stop the sweep early on first SLO failure
                        break
                if aborted:
                    break
        finally:
            if exp.teardown and exp.subject.provisioner is not None:
                await exp.subject.provisioner.teardown()
        return Run(
            run_id=self.run_id,
            experiment=exp.name,
            created_at=started,
            subject=exp.subject.name,
            trials=trials,
            passed=passed,
        )

    async def _run_trial(
        self, target: Target, profile: ResourceProfile, load: LoadProfile
    ) -> TrialResult:
        exp = self.experiment
        stats = ClientStats()
        cap = max(64, int(load.schedule.peak_level) * 2)
        limits = httpx.Limits(max_connections=cap, max_keepalive_connections=cap)
        # observer gets its own small pool so /metrics scraping never queues behind
        # load traffic on a saturated pool (P1: don't lose evidence at saturation)
        obs_limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
        timed: list[tuple[float, Outcome]] = []
        store: ProbeStore = {}
        probe_errors: dict[str, ProbeErrors] = {}
        measurement_end_s = 0.0
        cooldown_start_s: float | None = None

        # trust_env=False: the load generator connects DIRECTLY to the Subject's
        # base_url — never via an ambient HTTP(S)_PROXY/ALL_PROXY from the shell (a
        # stray proxy env would silently reroute or, if malformed, crash client
        # creation). A real proxy, if ever needed, should be an explicit Target field.
        async with (
            httpx.AsyncClient(limits=limits, http2=False, trust_env=False) as client,
            httpx.AsyncClient(limits=obs_limits, http2=False, trust_env=False) as obs_client,
        ):
            trial_ctx = TrialContext(
                target=target,
                client=client,
                run_id=self.run_id,
                resources=profile,
                load=load,
            )
            observer: asyncio.Task | None = None
            stop = asyncio.Event()
            primary_error: BaseException | None = None
            try:
                await exp.workload.setup(trial_ctx)
                ctx = ProbeContext(
                    target=target,
                    client=client,
                    t0=time.monotonic(),
                    stats=stats,
                    observer_client=obs_client,
                )
                observer = asyncio.create_task(
                    observe_loop(exp.probes, ctx, store, stop, exp.observe_interval_s)
                )
                drive = drive_open if load.model == "open" else drive_closed
                trial_stop = await drive(
                    exp.workload, ctx, load, self._cases, self._weights, self.run_id, timed
                )
                # Post-load samples remain in the raw series for cooldown/scale-down
                # charts, but summaries must describe only the load measurement window.
                measurement_end_s = time.monotonic() - ctx.t0
                await exp.workload.deactivate(trial_ctx)
                if exp.cooldown_s:
                    cooldown_start_s = time.monotonic() - ctx.t0
                    await asyncio.sleep(exp.cooldown_s)
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                if observer is not None:
                    stop.set()
                    probe_errors = await observer
                try:
                    await exp.workload.cleanup(trial_ctx)
                except BaseException as cleanup_error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(f"cleanup also failed: {cleanup_error!r}")

        trial = self._aggregate(
            profile,
            load,
            timed,
            store,
            probe_errors,
            measurement_end_s=measurement_end_s,
            cooldown_start_s=cooldown_start_s,
        )
        trial.stop = trial_stop  # how the trial ended (deadline / breaker) + enact census
        trial.outcomes = timed  # raw layer (incl. warmup/drops) — runio persists these
        return trial

    def _aggregate(
        self,
        profile: ResourceProfile,
        load: LoadProfile,
        timed: list[tuple[float, Outcome]],
        store: ProbeStore,
        probe_errors: dict[str, ProbeErrors] | None = None,
        *,
        measurement_end_s: float | None = None,
        cooldown_start_s: float | None = None,
    ) -> TrialResult:
        exp = self.experiment
        warmup = load.warmup_s
        closed = load.model == "closed"  # → the slice's latency carries the co_biased caveat
        outcomes = [o for (t, o) in timed if t >= warmup]

        overall = request_stats(outcomes, load.steady_s, closed=closed)

        # marginal pivot: per facet key, group outcomes by value → its own stats
        by_facet: dict[str, dict[str, RequestStats]] = {}
        facet_keys = {k for o in outcomes for k in o.facets}
        for key in facet_keys:
            groups: dict[str, list[Outcome]] = defaultdict(list)
            for o in outcomes:
                if key in o.facets:
                    groups[o.facets[key]].append(o)
            by_facet[key] = {
                val: request_stats(g, load.steady_s, closed=closed) for val, g in groups.items()
            }

        # per-stage pivot (multi-stage schedules only): group by the stage label
        # stamped at fire time; each stage's throughput uses its own duration so a
        # stepped/spike run yields a per-level capacity curve in one trial.
        by_stage: dict[str, RequestStats] = {}
        if load.schedule.is_multi_stage:
            # denominator = each stage's POST-warmup duration (outcomes are already
            # warmup-filtered), so a warmup-covered stage isn't under-counted
            durations = load.schedule.stage_durations(after_s=warmup)
            stage_groups: dict[str, list[Outcome]] = defaultdict(list)
            for o in outcomes:
                if o.stage is not None:
                    stage_groups[o.stage].append(o)
            by_stage = {
                label: request_stats(g, durations.get(label) or 1e-9, closed=closed)
                for label, g in stage_groups.items()
            }

        # unified metric registry: every report/SLO-visible metric → its descriptor.
        # (1) builtin request.* (duration_ms / error_rate / throughput_rps /
        # drop_rate). (2) per-request distributions: a Workload may declare
        # unit/source (describe()); undeclared keys (e.g. dynamic first_<event>_ms)
        # are inferred — always a distribution, source=client.
        registry: dict[str, MetricFamily] = {d.name: d for d in REQUEST_DESCRIPTORS}
        # per-request descriptor precedence: Workload-declared > framework (ttft_ms) > inferred
        known = {d.name: d for d in PER_REQUEST_DESCRIPTORS}
        known.update({m.name: m for m in exp.workload.describe()})
        for key in overall.metrics:
            registry[key] = known.get(
                key,
                MetricFamily(
                    name=key,
                    unit=unit_of(key),
                    side="request",
                    value_kind="distribution",
                    source="client",
                ),
            )

        # resource-side: each probe collapses its (steady) series → typed summaries
        # (gauge/counter), keyed <probe>.<metric>; FAMILY descriptors come from
        # describe() (deduped by family name — service is a label on the series, not it).
        probe_metrics: dict[str, MetricSummary] = {}
        series_out: dict[str, Series] = {}
        errors = probe_errors or {}
        for probe in exp.probes:
            registry.update({d.name: d for d in probe.describe()})  # by family (dedup)
            # group this probe's sampled series by extra-label-set: a common probe's bare
            # keys all land in the one () group; a fan-out probe's labeled keys
            # (cpu_m{pod="…"}) land in one group per pod. Each group then summarizes
            # exactly like a single probe did before — pod is just another label.
            groups: dict[tuple[tuple[str, str], ...], dict[str, list[Sample]]] = {}
            for (pname, key), samples in store.items():
                if pname != probe.name:
                    continue
                bare, extra = split_series(key)
                groups.setdefault(tuple(sorted(extra.items())), {})[bare] = samples
            for extra in sorted(groups):
                by_bare = groups[extra]
                labels = {**probe.labels, **dict(extra)}  # base {service} + e.g. {pod}
                own_steady: dict[str, list[Sample]] = {}
                for metric, spec in probe.families.items():
                    full = by_bare.get(metric, [])
                    sid = series_id(f"{probe.family}.{metric}", labels)
                    if full:
                        series_out[sid] = Series(metric, spec.unit, list(full))
                    own_steady[metric] = [
                        s
                        for s in full
                        if s.t >= warmup and (measurement_end_s is None or s.t <= measurement_end_s)
                    ]
                for bare, summary in probe.summarize(own_steady).items():
                    if probe.name in errors:
                        # the probe missed ticks — its series have holes; the value
                        # stands but a flat-looking trend may be a sampling artifact
                        summary = replace(summary, caveats=summary.caveats | {"probe_error"})
                    probe_metrics[series_id(f"{probe.family}.{bare}", labels)] = summary
            # the synthesized health series (`up`, see _observe): full series for §4's
            # outage view, gauge summary (mean = availability ratio, SLO-addressable as
            # `<family>.up{service=…}.mean`). No probe_error caveat — up IS that signal.
            up_samples = store.get((probe.name, "up"), [])
            if up_samples:
                up_fam = f"{probe.family}.up"
                sid = series_id(up_fam, probe.labels)
                series_out[sid] = Series("up", "", list(up_samples))
                measured_up = [
                    s
                    for s in up_samples
                    if s.t >= warmup and (measurement_end_s is None or s.t <= measurement_end_s)
                ]
                for _, summary in probe.summarize({"up": measured_up}).items():
                    probe_metrics[sid] = summary
                registry[up_fam] = MetricFamily(
                    name=up_fam,
                    unit="",
                    side="resource",
                    value_kind="gauge",
                    source=probe.source,
                    description="probe health (1 ok / 0 failed) — Prometheus `up` 的对应物；"
                    "mean 即观测可用率",
                    labels=frozenset(probe.labels),
                )

        return TrialResult(
            subject=exp.subject.name,
            resources=profile,
            load=load,
            overall=overall,
            by_facet=by_facet,
            probe_metrics=probe_metrics,
            series=series_out,
            by_stage=by_stage,
            metrics=registry,
            probe_errors=dict(errors),
            cooldown_start_s=cooldown_start_s,
        )
