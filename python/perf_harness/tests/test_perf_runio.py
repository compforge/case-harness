"""runio — the model layer on disk: run.json full serialization, outcomes.jsonl raw
layer, and load_run/load_outcomes reconstructing the model (and thus a working
MetricStore) offline. The report/CSVs are derived views; THESE are the analysis
contract, so the round-trip must be lossless for everything the store can address."""

import json

import pytest
from spec_case.model import Case

from perf_harness.drive.load import LoadProfile, Schedule
from perf_harness.drive.workload import Workload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.metric import series_id
from perf_harness.metric.store import MetricStore
from perf_harness.model import Outcome, ResourceProfile, SloAssertion, Target, WindowSelector
from perf_harness.observe import FamilySpec, Probe
from perf_harness.report import write_run
from perf_harness.runio import RUN_SCHEMA, load_outcomes, load_run
from perf_harness.slo import evaluate_slo


class _FakeTop(Probe):
    """Constant gauges with a service label — exercises labeled-series round-trip."""

    name = "top.chat"
    source = "k8s"
    _service = "chat"
    families = {"cpu_m": FamilySpec("millicores")}

    @property
    def family(self) -> str:
        return "top"

    async def sample(self, ctx):
        return {"cpu_m": 123.0}


class _WL(Workload):
    name = "w"

    async def fire(self, target, client, case, run_id):
        return Outcome(status=200, duration_ms=10.0, events=1, metrics={"ttft_ms": 5.0})


async def _run(tmp_path):
    exp = Experiment(
        subject=Subject("chat", Target(base_url="http://127.0.0.1:0")),
        workload=_WL(),
        resources=[ResourceProfile(workers=2, memory="2Gi")],
        loads=[
            LoadProfile(
                model="closed",
                schedule=Schedule.ramp_hold(2, 0.0, 0.3),
                abort_on_error_rate=0.5,
                breaker_min_n=5,
            )
        ],
        probes=[_FakeTop()],
        cases=[Case(id="a", input={}, facets={"difficulty": "simple"})],
        slo=[
            SloAssertion(metric="error_rate", op="lt", threshold=0.5),
            SloAssertion(metric="nonexistent_ms.p95", op="lt", threshold=1.0),  # → skipped
            SloAssertion(
                metric='top.cpu_m{service="chat"}.last',
                op="lte",
                threshold=123.0,
                window=WindowSelector(kind="cooldown"),
            ),
        ],
        observe_interval_s=0.1,
        cooldown_s=0.12,
        name="rt",
    )
    run = await Engine(exp, run_id="20260101-000000").run()
    write_run(run, str(tmp_path))
    return run, tmp_path / "rt" / "20260101-000000"


async def test_run_json_is_the_full_model(tmp_path):
    run, run_dir = await _run(tmp_path)
    doc = json.loads((run_dir / "run.json").read_text())
    assert doc["schema"] == RUN_SCHEMA
    t = doc["trials"][0]
    # everything the live model knows is on disk: identity, config, verdicts, metadata
    assert t["id"] == run.trials[0].label()
    assert t["arm"]["resources"]["workers"] == 2
    assert t["arm"]["resources"]["memory"] == "2Gi"
    assert t["arm"]["load"]["abort_on_error_rate"] == 0.5
    assert t["arm"]["load"]["breaker_min_n"] == 5
    assert t["stop"]["reason"] == "deadline"
    states = {(c["metric"], c["window"]["kind"]): c["state"] for c in t["slo"]}
    assert states == {
        ("error_rate", "measurement"): "pass",
        ("nonexistent_ms.p95", "measurement"): "skipped",
        ('top.cpu_m{service="chat"}.last', "cooldown"): "pass",
    }
    windows = {window["id"]: window for window in t["windows"]}
    assert "cooldown" in windows
    assert t["registry"]["ttft_ms"]["unit"] == "ms"  # metric metadata persisted
    assert windows["measurement"]["request"]["n"] == run.trials[0].measurement.request.n
    assert "simple" in windows["measurement"]["by_facet"]["difficulty"]
    sid = series_id("top.cpu_m", {"service": "chat"})
    assert windows["measurement"]["probe_metrics"][sid]["kind"] == "gauge"
    assert windows["measurement"]["probe_metrics"][sid]["peak"] == 123.0


async def test_load_run_round_trips_the_store(tmp_path):
    run, run_dir = await _run(tmp_path)
    loaded = load_run(run_dir)
    assert loaded.run_id == run.run_id and len(loaded.trials) == 1
    live, offline = run.trials[0], loaded.trials[0]
    # the offline MetricStore answers the SAME addressed reads as the live one
    refs = [
        "request.error_rate.value",
        "request.duration_ms.p99",
        "ttft_ms.p95",
        'duration_ms{difficulty="simple"}.p50',
        'top.cpu_m{service="chat"}.peak',
    ]
    ls, os_ = MetricStore(run.trials), MetricStore(loaded.trials)
    for ref in refs:
        assert ls.query(live, ref) == os_.query(offline, ref), ref
    # series came back from timeseries.csv with the family's unit
    sid = series_id("top.cpu_m", {"service": "chat"})
    assert offline.series[sid].unit == "millicores"
    assert [s.value for s in offline.series[sid].samples] == [
        s.value for s in live.series[sid].samples
    ]
    assert [s.t for s in offline.series[sid].samples] == [s.t for s in live.series[sid].samples]
    assert offline.metrics["top.cpu_m"].labels == live.metrics["top.cpu_m"].labels
    # stop/slo verdicts survive (offline SLO re-reads agree)
    assert offline.stop == live.stop
    assert [(w.id, w.start_s, w.end_s) for w in offline.windows] == [
        (w.id, w.start_s, w.end_s) for w in live.windows
    ]
    assert [c.state for c in offline.slo] == [c.state for c in live.slo]
    assert [c.assertion.window for c in offline.slo] == [c.assertion.window for c in live.slo]
    assert evaluate_slo(offline, [offline.slo[-1].assertion])[0].passed


async def test_outcomes_jsonl_is_the_request_raw_layer(tmp_path):
    run, run_dir = await _run(tmp_path)
    live = run.trials[0]
    by_trial = load_outcomes(run_dir)
    rows = by_trial[live.label()]
    # one record per recorded fire, in order, incl. warmup (raw layer ≥ post-warmup n)
    assert len(rows) == len(live.outcomes) >= live.measurement.request.n
    t0, o0 = rows[0]
    assert o0.status == 200 and o0.ok and o0.case_id == "a"
    assert o0.facets == {"difficulty": "simple"}
    assert o0.metrics["ttft_ms"] == 5.0  # per_request raw values survive


async def test_load_run_rejects_unknown_schema(tmp_path):
    _, run_dir = await _run(tmp_path)
    doc = json.loads((run_dir / "run.json").read_text())
    doc["schema"] = 999
    (run_dir / "run.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="schema"):
        load_run(run_dir)


async def test_cli_report_rerenders_from_model_layer(tmp_path):
    # the rendering is a pure downstream of the model layer: delete the html, re-render
    # from run.json/timeseries.csv alone — no engine, no re-press
    from perf_harness import cli

    _, run_dir = await _run(tmp_path)
    (run_dir / "report.html").unlink()
    assert cli.main(["report", str(run_dir)]) == 0
    assert (run_dir / "report.html").exists()


async def test_probe_errors_round_trip(tmp_path):
    # observation-failure census survives the disk round-trip: an offline reader can
    # tell "broken observability" from "calm data" without the live process
    from perf_harness.observe import Probe

    class _Down(Probe):
        name = "metrics.chat"
        source = "http"
        _service = "chat"
        families = {"x": FamilySpec("count")}

        @property
        def family(self):
            return "metrics"

        async def sample(self, ctx):
            raise RuntimeError("endpoint down")

    exp = Experiment(
        subject=Subject("chat", Target(base_url="http://127.0.0.1:0")),
        workload=_WL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.2))],
        probes=[_Down()],
        observe_interval_s=0.05,
        name="pe",
    )
    run = await Engine(exp, run_id="20260101-000001").run()
    write_run(run, str(tmp_path))
    loaded = load_run(tmp_path / "pe" / "20260101-000001")
    pe = loaded.trials[0].probe_errors["metrics.chat"]
    assert pe.failures >= 1 and pe.ticks >= pe.failures and "down" in pe.last
