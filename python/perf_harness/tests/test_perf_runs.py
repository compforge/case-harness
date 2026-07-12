import json

from perf_harness.drive.load import LoadProfile, Schedule
from perf_harness.drive.workload import MockWorkload, Workload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.model import (
    Outcome,
    ResourceProfile,
    Target,
    make_run_id,
)
from perf_harness.report import write_run


def _subject() -> Subject:
    return Subject("chat", Target(base_url="http://127.0.0.1:0"))


def test_make_run_id_format():
    rid = make_run_id()
    assert len(rid) == len("20260101-000000")  # YYYYMMDD-HHMMSS


async def test_write_run_lays_out_experiment_dir(tmp_path):
    experiment = Experiment(
        subject=_subject(),
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile(workers=2)],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(2, 0.0, 0.2))],
        name="chat-sizing",
    )
    engine = Engine(experiment, run_id="20260101-000000")
    run = await engine.run()
    assert run.experiment == "chat-sizing" and run.run_id == "20260101-000000"
    write_run(run, str(tmp_path))

    run_dir = tmp_path / "chat-sizing" / "20260101-000000"
    assert run_dir.is_dir()
    for f in ("report.md", "summary.csv", "by_facet.csv", "timeseries.csv", "run.json"):
        assert (run_dir / f).exists()

    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["experiment"] == "chat-sizing"
    assert meta["run_id"] == "20260101-000000"
    assert meta["n_trials"] == len(run.trials)

    # run.jsonl at the experiment level, one line per run (accumulates)
    log = tmp_path / "chat-sizing" / "run.jsonl"
    assert log.exists()
    assert len(log.read_text().splitlines()) == 1


async def test_run_id_reaches_fire(tmp_path):
    seen: list[str] = []

    class RecordingWorkload(Workload):
        name = "rec"

        async def fire(self, target, client, case, run_id):
            seen.append(run_id)
            return Outcome(ok=True, status=200, duration_ms=1.0)

    experiment = Experiment(
        subject=_subject(),
        workload=RecordingWorkload(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.1))],
    )
    await Engine(experiment, run_id="RID-123").run()
    assert seen and all(r == "RID-123" for r in seen)
