from perf_harness.drive.load import LoadProfile, Schedule, Stage
from perf_harness.drive.workload import MockWorkload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.model import ResourceProfile, Target


def _stepped() -> Schedule:
    return Schedule(
        stages=(
            Stage(over_s=1, to_level=10, kind="ramp"),
            Stage(over_s=2, to_level=10, kind="hold"),
            Stage(over_s=1, to_level=30, kind="ramp"),
            Stage(over_s=2, to_level=30, kind="hold"),
        )
    )


def test_stage_labels_and_durations():
    s = _stepped()
    assert s.is_multi_stage  # two holds
    assert s.stage_label(0.5) == "ramp→10"  # [0,1)
    assert s.stage_label(2.0) == "hold@10"  # [1,3)
    assert s.stage_label(3.5) == "ramp→30"  # [3,4)
    assert s.stage_label(5.0) == "hold@30"  # [4,6)
    assert s.stage_durations() == {
        "ramp→10": 1,
        "hold@10": 2,
        "ramp→30": 1,
        "hold@30": 2,
    }


def test_stage_durations_after_warmup():
    s = _stepped()  # ramp→10[0,1) hold@10[1,3) ramp→30[3,4) hold@30[4,6)
    # warmup 2s: ramp→10 fully eaten, 1s of hold@10 eaten
    d = s.stage_durations(after_s=2.0)
    assert d["ramp→10"] == 0
    assert d["hold@10"] == 1
    assert d["ramp→30"] == 1
    assert d["hold@30"] == 2
    assert s.stage_durations()["hold@10"] == 2  # default (no warmup) unchanged


def test_ramp_hold_is_single_stage():
    assert not Schedule.ramp_hold(10, 1, 5).is_multi_stage  # one hold
    assert Schedule.spike(5, 50, 1, 1, 1).is_multi_stage  # three holds


def test_stage_name_overrides_auto_label():
    assert Stage(over_s=1, to_level=10, kind="hold", name="warm").label == "warm"
    assert Stage(over_s=1, to_level=10, kind="hold").label == "hold@10"


async def test_engine_pivots_by_stage_for_stepped_schedule():
    # open 20→40 step; each hold is its own per-level slice via by_stage
    sched = Schedule(
        stages=(
            Stage(over_s=0.01, to_level=20, kind="ramp"),
            Stage(over_s=0.5, to_level=20, kind="hold"),
            Stage(over_s=0.01, to_level=40, kind="ramp"),
            Stage(over_s=0.5, to_level=40, kind="hold"),
        )
    )
    exp = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile(workers=2)],
        loads=[LoadProfile(model="open", schedule=sched)],  # warmup_s defaults to 0
    )
    r = (await Engine(exp).run()).trials[0]
    assert "hold@20" in r.by_stage and "hold@40" in r.by_stage
    # the 40 rps hold sends ~2x the 10*... requests of the 20 rps hold in the same window
    assert r.by_stage["hold@40"].n > r.by_stage["hold@20"].n
    assert r.by_stage["hold@40"].throughput_rps > r.by_stage["hold@20"].throughput_rps


async def test_single_stage_run_has_no_by_stage():
    exp = Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile(workers=2)],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(3, 0.0, 0.3))],
    )
    r = (await Engine(exp).run()).trials[0]
    assert r.by_stage == {}
