from harness_common.case import Case
from harness_common.overlay import Overlay

from perf_harness.drive.load import LoadProfile, Schedule
from perf_harness.drive.workload import MockWorkload, Workload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.model import Outcome, ResourceProfile, Target


def _subject() -> Subject:
    return Subject("mock", Target(base_url="http://127.0.0.1:0"))


async def test_facets_pivot_and_weighting():
    experiment = Experiment(
        subject=_subject(),
        workload=MockWorkload(),
        resources=[ResourceProfile(workers=2)],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(4, 0.0, 0.5))],
        cases=[
            Case(id="simple", input={"ms": 2}, facets={"difficulty": "simple"}),
            Case(id="complex", input={"ms": 20}, facets={"difficulty": "complex"}),
        ],
        mix=Overlay({"simple": 80, "complex": 20}),
    )
    r = (await Engine(experiment).run()).trials[0]

    assert r.overall.n > 0
    assert "difficulty" in r.by_facet
    by = r.by_facet["difficulty"]
    assert set(by) <= {"simple", "complex"}
    # every outcome is tagged → the pivot partitions the whole trial
    assert sum(s.n for s in by.values()) == r.overall.n
    # both present with enough fires; weight 80/20 → more simple; ms 20 > 2 → higher p50
    assert "simple" in by and "complex" in by
    assert by["simple"].n > by["complex"].n
    assert by["complex"].p50_ms > by["simple"].p50_ms


class _SlowWorkload(Workload):
    name = "slow"

    async def fire(self, target, client, case, run_id):
        import asyncio

        await asyncio.sleep(0.05)
        return Outcome(status=200, duration_ms=50)


async def test_open_loop_drops_are_separate_not_latency_samples():
    # 200 rps open against a 50ms workload capped at 2 inflight → most arrivals
    # are client_saturated drops. Drops must NOT contaminate latency (they'd drag
    # p50 toward 0) and are counted separately (n_dropped), attributed per facet.
    experiment = Experiment(
        subject=_subject(),
        workload=_SlowWorkload(),
        resources=[ResourceProfile(workers=2)],
        loads=[
            LoadProfile(model="open", schedule=Schedule.ramp_hold(200, 0.0, 0.4), max_inflight=2)
        ],
        cases=[Case(id="x", input={}, facets={"difficulty": "simple"})],
    )
    r = (await Engine(experiment).run()).trials[0]
    assert r.overall.n_dropped > 0  # saturation happened
    assert r.overall.n > 0  # some requests were actually sent
    # drops are out of the latency histogram → fired ~50ms requests set the
    # percentile, not the 0ms drops (the coordinated-omission bug this fixes)
    assert r.overall.p50_ms >= 40
    # client_saturated is a drop, not a server error
    assert "client_saturated" not in r.overall.error_breakdown
    # drops attributed to the Case's facet → per-facet sent + dropped both reconcile
    assert "difficulty" in r.by_facet
    assert sum(s.n for s in r.by_facet["difficulty"].values()) == r.overall.n
    assert sum(s.n_dropped for s in r.by_facet["difficulty"].values()) == r.overall.n_dropped


async def test_no_cases_is_anonymous_no_facets():
    experiment = Experiment(
        subject=_subject(),
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile(workers=2)],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(2, 0.0, 0.2))],
    )
    r = (await Engine(experiment).run()).trials[0]
    assert r.overall.n > 0
    assert r.by_facet == {}
