import asyncio

import pytest
from spec_case.model import Case

from perf_harness.drive.load import LoadProfile, Pacing, Schedule
from perf_harness.drive.workload import MockWorkload, Workload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.model import Outcome, ResourceProfile, SloAssertion, Target
from perf_harness.observe import ClientProbe, FamilySpec, Probe


class _AlwaysFailWL(Workload):
    """Every fire returns 500 → judge fails → 100% error rate (drives the breaker)."""

    name = "failwl"

    async def fire(self, target, client, case, run_id):
        await asyncio.sleep(0.001)
        return Outcome(status=500, duration_ms=1.0)


class _RaisesWL(Workload):
    name = "raises"

    async def fire(self, target, client, case, run_id):
        raise RuntimeError("transport detail")


async def test_engine_smoke_offline():
    subject = Subject("mock", Target(base_url="http://127.0.0.1:0"))
    experiment = Experiment(
        subject=subject,
        workload=MockWorkload(base_ms=5),
        resources=[ResourceProfile(workers=2)],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(3, 0.0, 0.4))],
        probes=[ClientProbe()],
        observe_interval_s=0.05,
    )
    run = await Engine(experiment).run()

    assert run.run_id and run.subject == "mock"
    assert len(run.trials) == 1
    r = run.trials[0]
    assert r.overall.n > 0
    assert r.overall.n_ok == r.overall.n
    assert r.overall.error_rate == 0.0
    assert r.overall.throughput_rps > 0
    # client-side probe produced a time-series within the trial
    assert any(k.startswith("client.") for k in r.series)
    assert "client.inflight" in r.probe_metrics  # typed gauge summary
    assert r.probe_metrics["client.inflight"].peak is not None


async def test_engine_stamps_case_id_and_preserves_exception_detail():
    experiment = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=_RaisesWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.05))],
        cases=[Case(id="transport-case", input={})],
        observe_interval_s=0.01,
    )

    trial = (await Engine(experiment).run()).trials[0]
    assert trial.outcomes
    outcomes = [outcome for _, outcome in trial.outcomes]
    assert {outcome.case_id for outcome in outcomes} == {"transport-case"}
    assert {outcome.meta["exc"] for outcome in outcomes} == {"RuntimeError"}
    assert {outcome.meta["exc_detail"] for outcome in outcomes} == {"transport detail"}


async def test_engine_sweeps_grid():
    subject = Subject("mock", Target(base_url="http://127.0.0.1:0"))
    experiment = Experiment(
        subject=subject,
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile(workers=2), ResourceProfile(workers=4)],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(2, 0.0, 0.2))],
        probes=[ClientProbe()],
        observe_interval_s=0.05,
    )
    run = await Engine(experiment).run()
    # 2 constraints × 1 load = 2 trials
    assert len(run.trials) == 2
    assert {r.resources.workers for r in run.trials} == {2, 4}


def test_schedule_ramps_then_holds():
    s = Schedule.ramp_hold(20, ramp_s=2.0, hold_s=5.0)
    assert s.intensity(0.0) == 0.0  # ramp starts at 0
    assert s.intensity(1.0) == 10.0  # halfway up a 0→20 ramp
    assert s.intensity(2.0) == 20.0  # top of ramp
    assert s.intensity(4.0) == 20.0  # holding
    assert s.intensity(99.0) == 20.0  # past the end → hold final
    assert s.peak_level == 20.0
    assert s.total_s == 7.0


def test_schedule_no_ramp_is_flat():
    s = Schedule.ramp_hold(8, ramp_s=0.0, hold_s=1.0)
    assert s.intensity(0.0) == 8.0
    assert s.intensity(0.5) == 8.0


def test_schedule_spike_rises_and_falls():
    s = Schedule.spike(base=5, peak=50, base_s=1, rise_s=1, peak_s=1)
    assert s.intensity(0.5) == 5  # baseline
    assert s.intensity(1.5) == 27.5  # mid-rise 5→50
    assert s.intensity(2.5) == 50  # at peak
    assert s.intensity(3.5) == 27.5  # mid-fall 50→5
    assert s.peak_level == 50


def test_pacing_modes():
    assert Pacing().wait_s(0.1) == 0.0  # none → back-to-back
    assert Pacing(kind="constant", secs=0.5).wait_s(0.1) == 0.5
    assert Pacing(kind="constant_pacing", secs=1.0).wait_s(0.3) == 0.7  # 1.0 - fire 0.3
    assert Pacing(kind="constant_pacing", secs=1.0).wait_s(2.0) == 0.0  # fire overran → no wait
    w = Pacing(kind="between", secs=0.1, max_secs=0.3).wait_s(0.0)
    assert 0.1 <= w <= 0.3


async def test_circuit_breaker_aborts_trial_on_error_rate():
    # a 5s steady at concurrency 4 would normally fire thousands; the breaker should
    # trip within the first ~0.1s supervisor tick once error rate ≥ 50% (min_n=5),
    # so the trial ends almost immediately and is flagged aborted.
    subject = Subject("b", Target(base_url="http://127.0.0.1:0"))
    exp = Experiment(
        subject=subject,
        workload=_AlwaysFailWL(),
        resources=[ResourceProfile()],
        loads=[
            LoadProfile(
                model="closed",
                schedule=Schedule.ramp_hold(4, 0.0, 5.0),
                abort_on_error_rate=0.5,
                breaker_min_n=5,
            )
        ],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    # structured TrialStop (the truth); aborted is a convenience alias over stop.early
    assert r.aborted is True and r.stop.early is True
    assert r.stop.reason == "error_rate"
    snap = r.stop.snapshot
    assert snap is not None  # the trip view (not post-warmup overall)
    assert snap.sent >= 5 and snap.error_rate >= 0.5 and snap.threshold == 0.5
    # fast requests drain instantly on stop → nothing force-cancelled
    assert r.stop.force_cancelled is False and r.stop.interrupted == 0
    assert r.overall.error_rate == 1.0
    assert r.overall.n < 3000  # stopped early — nowhere near a full 5s window


async def test_no_breaker_runs_full_window_not_aborted():
    # without abort_on_error_rate, even an all-failing workload runs the full (short)
    # window and ends with reason="deadline" — the breaker is opt-in.
    subject = Subject("b", Target(base_url="http://127.0.0.1:0"))
    exp = Experiment(
        subject=subject,
        workload=_AlwaysFailWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(2, 0.0, 0.2))],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    assert r.aborted is False
    assert r.stop.reason == "deadline" and r.stop.snapshot is None
    assert r.overall.error_rate == 1.0  # still all errors, just not auto-stopped


class _SlowWL(Workload):
    """Each fire sleeps 2s — long enough to still be in flight when a short trial ends."""

    name = "slowwl"

    async def fire(self, target, client, case, run_id):
        await asyncio.sleep(2.0)
        return Outcome(status=200, duration_ms=2000.0)


async def test_hard_stop_force_cancels_inflight_and_counts_interrupted():
    # graceful_stop_s=0 → at the deadline the in-flight (slow) requests are force-
    # cancelled and counted as `interrupted`, and a cancelled request NEVER becomes a
    # latency sample (overall.n stays 0). Validates the A4 invariant + the census.
    subject = Subject("h", Target(base_url="http://127.0.0.1:0"))
    exp = Experiment(
        subject=subject,
        workload=_SlowWL(),
        resources=[ResourceProfile()],
        loads=[
            LoadProfile(
                model="closed",
                schedule=Schedule.ramp_hold(3, 0.0, 0.2),
                graceful_stop_s=0.0,  # hard stop: no drain
            )
        ],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    assert r.stop.reason == "deadline"  # not a breaker — just hit the (short) deadline
    assert r.stop.force_cancelled is True
    assert r.stop.interrupted == 3 and r.stop.inflight_at_stop == 3
    assert r.overall.n == 0  # the 3 cut requests are NOT latency samples


async def test_engine_open_model_smoke():
    subject = Subject("mock", Target(base_url="http://127.0.0.1:0"))
    experiment = Experiment(
        subject=subject,
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile(workers=2)],
        loads=[
            LoadProfile(
                model="open",
                schedule=Schedule.ramp_hold(40, 0.2, 0.6),
                warmup_s=0.2,
            )
        ],
        probes=[ClientProbe()],
        observe_interval_s=0.05,
    )
    run = await Engine(experiment).run()
    r = run.trials[0]
    # open-loop produced steady-window outcomes at roughly the held rate
    assert r.overall.n > 0
    assert r.overall.error_rate == 0.0
    assert r.overall.throughput_rps > 0


async def test_trial_hooks_wrap_load_and_cooldown_only_extends_raw_series():
    state = {"post_load": False}
    events: list[str] = []

    class LifecycleWorkload(Workload):
        async def setup(self, ctx):
            events.append("setup")

        async def fire(self, target, client, case, run_id):
            return Outcome(status=200, duration_ms=1.0)

        async def deactivate(self, ctx):
            events.append("deactivation")
            state["post_load"] = True

        async def cleanup(self, ctx):
            events.append("cleanup")

    class PhaseProbe(Probe):
        name = "phase"
        source = "test"
        families = {"post_load": FamilySpec("count")}

        async def sample(self, ctx):
            return {"post_load": float(state["post_load"])}

    exp = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=LifecycleWorkload(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.12))],
        probes=[PhaseProbe()],
        observe_interval_s=0.03,
        cooldown_s=0.12,
        slo=[
            SloAssertion(
                "phase.post_load.last",
                "gte",
                1,
                window="cooldown",
            )
        ],
    )
    run = await Engine(exp).run()
    trial = run.trials[0]
    assert events == ["setup", "deactivation", "cleanup"]
    assert trial.probe_metrics["phase.post_load"].peak == 0.0
    assert any(s.value == 1.0 for s in trial.series["phase.post_load"].samples)
    assert trial.cooldown_start_s is not None
    assert run.passed and trial.slo[0].passed and trial.slo[0].observed == 1.0


async def test_cleanup_runs_when_setup_fails():
    events: list[str] = []

    class BrokenSetup(Workload):
        async def setup(self, ctx):
            events.append("setup")
            raise RuntimeError("setup failed")

        async def fire(self, target, client, case, run_id):
            return Outcome(status=200, duration_ms=1.0)

        async def cleanup(self, ctx):
            events.append("cleanup")

    exp = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=BrokenSetup(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.1))],
    )
    with pytest.raises(RuntimeError, match="setup failed"):
        await Engine(exp).run()
    assert events == ["setup", "cleanup"]


async def test_cleanup_error_does_not_hide_setup_error():
    class BrokenLifecycle(Workload):
        async def setup(self, ctx):
            raise RuntimeError("setup failed")

        async def fire(self, target, client, case, run_id):
            return Outcome(status=200, duration_ms=1.0)

        async def cleanup(self, ctx):
            raise RuntimeError("cleanup failed")

    exp = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=BrokenLifecycle(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.1))],
    )
    with pytest.raises(RuntimeError, match="setup failed") as caught:
        await Engine(exp).run()
    assert any("cleanup failed" in note for note in caught.value.__notes__)


async def test_cooldown_slo_missing_data_fails_closed():
    class EmptyProbe(Probe):
        name = "empty"
        source = "test"
        families = {"value": FamilySpec("count")}

        async def sample(self, ctx):
            return {}

    exp = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=MockWorkload(base_ms=1),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.05))],
        probes=[EmptyProbe()],
        observe_interval_s=0.01,
        cooldown_s=0.03,
        slo=[SloAssertion("empty.value.last", "lte", 0, window="cooldown")],
    )
    run = await Engine(exp).run()
    assert run.trials[0].slo[0].skipped
    assert not run.passed
