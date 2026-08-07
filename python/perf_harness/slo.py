"""SLO evaluation — the per-run gate (aggregate verdict), distinct from the
per-request ``Workload.judge``.

Pure functions over already-aggregated ``TrialResult``s: read each metric through
the ``MetricStore`` (the one addressing face) and compare to a threshold, producing
THREE-state ``SloCheck``s. Purity means a run's pass/fail can be recomputed offline.

A metric ref is ``<name>{labels}.<stat>`` (or an undotted builtin alias like
``p99_ms``). service / facet / stage are all LABELS — the store routes on them. A
``Missing`` read (the slice/metric was absent on this trial) becomes a *skipped*
check: NOT a pass. It never lets a trial count as confirmed capacity, and under
``strict_slo`` it fails the run (a Prometheus alert may no-fire on empty; a CI gate
must not silently pass). The builtin descriptors + the request-slice projection
live in ``store.py`` (the metric layer); import them from there.
"""

from __future__ import annotations

from perf_harness.metric import Missing
from perf_harness.metric.store import MetricStore
from perf_harness.model import SloAssertion, SloCheck, TrialResult


def _compare(observed: float, op: str, threshold: float | tuple[float, float]) -> bool:
    if op == "between":
        lo, hi = threshold  # type: ignore[misc]
        return lo <= observed <= hi
    return {
        "lt": observed < threshold,
        "lte": observed <= threshold,
        "gt": observed > threshold,
        "gte": observed >= threshold,
    }[op]


def evaluate_slo(trial: TrialResult, assertions: list[SloAssertion]) -> list[SloCheck]:
    """Evaluate every assertion that gates this trial (``level`` filter), reading each
    metric through the MetricStore. A ``Missing`` read (slice/metric absent on this
    trial) → a *skipped* check (``observed=None``) — never a pass."""
    store = MetricStore([trial])
    checks: list[SloCheck] = []
    level = trial.load.schedule.peak_level
    for a in assertions:
        if a.level is not None and a.level != level:
            continue  # assertion gates a different load level
        if a.window == "cooldown":
            read = (
                store.query_window(trial, a.metric, start_s=trial.cooldown_start_s)
                if trial.cooldown_start_s is not None
                else Missing("no_data")
            )
        else:
            read = store.query(trial, a.metric)
        if isinstance(read, Missing):
            checks.append(SloCheck(a, observed=None, state="skipped"))
            continue
        passed = _compare(read, a.op, a.threshold)
        checks.append(SloCheck(a, observed=read, state="pass" if passed else "fail"))
    return checks


def slo_aware_capacity(trials: list[TrialResult]) -> dict[str, float | None]:
    """Per resource profile: the highest *complete* load level whose trial met ALL
    its SLOs. A skipped check or early-stopped partial window cannot confirm
    capacity. ``None`` if no complete level passed / no SLOs."""
    best: dict[str, float | None] = {}
    for t in trials:
        c = t.resources.label()
        best.setdefault(c, None)
        if not t.stop.early and t.slo and t.slo_passed:
            lvl = t.load.schedule.peak_level
            if best[c] is None or lvl > best[c]:
                best[c] = lvl
    return best
