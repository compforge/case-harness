import pytest

from perf_harness.cli import main
from perf_harness.config import load_experiment
from perf_harness.drive.load import LoadProfile, Schedule
from perf_harness.drive.workload import MockWorkload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.metric import MetricFamily
from perf_harness.model import (
    RequestStats,
    ResourceProfile,
    Sample,
    Series,
    SloAssertion,
    Target,
    TrialResult,
)
from perf_harness.slo import evaluate_slo, slo_aware_capacity


def _trial(level: float, p99: float, *, err: float = 0.0, n_dropped: int = 0) -> TrialResult:
    stats = RequestStats(
        n=100,
        n_ok=int(round(100 * (1 - err))),
        throughput_rps=level,
        p50_ms=p99 / 2,
        p95_ms=p99,
        p99_ms=p99,
        error_rate=err,
        error_breakdown={},
        n_dropped=n_dropped,
    )
    return TrialResult(
        subject="s",
        resources=ResourceProfile(workers=2),
        load=LoadProfile(model="open", schedule=Schedule.ramp_hold(level, 0.0, 1.0)),
        overall=stats,
        by_facet={},
        series={},
    )


# ---- evaluate_slo (pure) ----


def test_slo_pass_and_fail():
    t = _trial(40, p99=100)
    assert evaluate_slo(t, [SloAssertion("p99_ms", "lt", 200)])[0].passed
    c = evaluate_slo(t, [SloAssertion("p99_ms", "lt", 50)])[0]
    assert not c.passed and c.observed == 100


def test_slo_between_and_gte():
    t = _trial(40, p99=100)
    assert evaluate_slo(t, [SloAssertion("throughput_rps", "gte", 40)])[0].passed
    assert evaluate_slo(t, [SloAssertion("p99_ms", "between", (50, 150))])[0].passed
    assert not evaluate_slo(t, [SloAssertion("p99_ms", "between", (0, 50))])[0].passed


def test_slo_level_filter_gates_only_matching_trial():
    a = SloAssertion("p99_ms", "lt", 2000, level=40)
    assert evaluate_slo(_trial(10, 100), [a]) == []  # level 10 not gated
    assert not evaluate_slo(_trial(40, 5000), [a])[0].passed  # level 40 gated, fails


def test_slo_missing_label_slice_is_skipped():
    # a facet label whose value no run produced → SKIPPED (three-state): not a failure,
    # but not a pass either — a skip never counts as green
    c = evaluate_slo(_trial(40, 100), [SloAssertion('p99_ms{difficulty="x"}', "lt", 1)])[0]
    assert c.observed is None and c.skipped and not c.passed


def test_cooldown_slo_reduces_exact_resource_series_labels():
    t = _trial(40, p99=100)
    sid = 'metrics.task_count{service="worker",state="running",task_type="batch"}'
    t.metrics = {
        "metrics.task_count": MetricFamily(
            "metrics.task_count", "count", "resource", "gauge", "http"
        )
    }
    t.series = {
        sid: Series(
            "task_count",
            "count",
            [
                Sample(0.5, 10.0),
                Sample(1.1, 3.0),
                Sample(1.2, 0.0),
            ],
        ),
        'metrics.up{service="worker"}': Series(
            "up",
            "",
            [Sample(1.1, 1.0), Sample(1.2, 1.0)],
        ),
    }
    t.cooldown_start_s = 1.0
    ref = f"{sid}.last"
    check = evaluate_slo(t, [SloAssertion(ref, "lte", 0, window="cooldown")])[0]
    assert check.passed and check.observed == 0.0


def test_slo_facet_label_reads_the_facet_slice():
    t = _trial(40, p99=100)  # overall p99 = 100
    simple = RequestStats(
        n=10,
        n_ok=10,
        throughput_rps=5,
        p50_ms=10,
        p95_ms=20,
        p99_ms=30,
        error_rate=0.0,
        error_breakdown={},
    )
    t.by_facet = {"difficulty": {"simple": simple}}
    # the facet label selects the `simple` slice → p99 there is 30, not the overall 100
    c = evaluate_slo(t, [SloAssertion('p99_ms{difficulty="simple"}', "lt", 50)])[0]
    assert c.observed == 30 and c.passed
    # while overall (no label) sees 100 → fails the same budget
    assert not evaluate_slo(t, [SloAssertion("p99_ms", "lt", 50)])[0].passed


def test_slo_aware_capacity_is_highest_passing_level():
    a = SloAssertion("p99_ms", "lt", 2000)
    t10, t40 = _trial(10, 100), _trial(40, 5000)
    t10.slo = evaluate_slo(t10, [a])
    t40.slo = evaluate_slo(t40, [a])
    assert slo_aware_capacity([t10, t40]) == {"w2": 10}


# ---- config parse + fail-fast ----

_BASE = """
subject: { name: s, base_url: "http://x" }
resources: [ {} ]
workload: { name: mock }
"""


def _write(tmp_path, extra: str) -> str:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_BASE + extra)
    return str(cfg)


def test_parse_slo_and_abort(tmp_path):
    extra = (
        "abort_on_fail: true\n"
        "slo:\n"
        "  - { metric: p99_ms, lt: 2000 }\n"
        "  - { metric: error_rate, lt: 0.01, level: 40 }\n"
        "load: { model: open, levels: [40], steady_s: 0.1 }\n"
    )
    exp, _ = load_experiment(_write(tmp_path, extra))
    assert exp.abort_on_fail
    assert len(exp.slo) == 2
    assert exp.slo[0].op == "lt" and exp.slo[0].threshold == 2000
    assert exp.slo[1].level == 40


def test_parse_cooldown_slo(tmp_path):
    extra = (
        "cooldown_s: 1\n"
        "slo:\n"
        "  - { metric: client.inflight.last, window: cooldown, lte: 0 }\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    exp, _ = load_experiment(_write(tmp_path, extra))
    assert exp.slo[0].window == "cooldown"


def test_cooldown_slo_accepts_resource_series_labels(tmp_path):
    extra = (
        "cooldown_s: 1\n"
        "observe:\n"
        "  - name: worker\n"
        "    probes:\n"
        "      - name: prometheus\n"
        "        queries:\n"
        "          - { name: task_count, promql: 'sum by (task_type, state) (task_count)', "
        "kind: gauge, labels: [task_type, state] }\n"
        "slo:\n"
        '  - { metric: \'prometheus.task_count{service="worker",'
        'task_type="batch",state="running"}.last\', window: cooldown, lte: 0 }\n'
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    exp, _ = load_experiment(_write(tmp_path, extra))
    assert exp.slo[0].window == "cooldown"


def test_cooldown_slo_rejects_unknown_resource_label(tmp_path):
    extra = (
        "cooldown_s: 1\n"
        "observe:\n"
        "  - name: worker\n"
        "    probes:\n"
        "      - name: prometheus\n"
        "        queries:\n"
        "          - { name: task_count, promql: 'sum by (task_type, state) (task_count)', "
        "kind: gauge, labels: [task_type, state] }\n"
        "slo:\n"
        '  - { metric: \'prometheus.task_count{service="worker",'
        'task_tipe="batch",state="running"}.last\', window: cooldown, lte: 0 }\n'
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="unknown labels.*task_tipe"):
        load_experiment(_write(tmp_path, extra))


def test_cooldown_slo_skips_stale_or_failed_probe_data():
    t = _trial(40, p99=100)
    sid = 'metrics.task_count{service="worker",state="running",task_type="batch"}'
    t.metrics = {
        "metrics.task_count": MetricFamily(
            "metrics.task_count",
            "count",
            "resource",
            "gauge",
            "http",
            labels=frozenset({"service", "state", "task_type"}),
        )
    }
    t.cooldown_start_s = 1.0
    t.series = {
        sid: Series("task_count", "count", [Sample(1.1, 0.0)]),
        'metrics.up{service="worker"}': Series("up", "", [Sample(1.1, 1.0), Sample(1.2, 1.0)]),
    }
    assertion = SloAssertion(f"{sid}.last", "lte", 0, window="cooldown")
    assert evaluate_slo(t, [assertion])[0].skipped

    t.series['metrics.up{service="worker"}'].samples[-1] = Sample(1.1, 0.0)
    assert evaluate_slo(t, [assertion])[0].skipped


def test_request_slo_unknown_facet_key_still_fails_fast(tmp_path):
    extra = (
        "slo: [ { metric: 'p99_ms{unknown=\"x\"}', lte: 100 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="facet unknown=x unknown"):
        load_experiment(_write(tmp_path, extra))


def test_cooldown_slo_requires_cooldown(tmp_path):
    extra = (
        "slo: [ { metric: client.inflight.last, window: cooldown, lte: 0 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="requires cooldown_s"):
        load_experiment(_write(tmp_path, extra))


def test_cooldown_slo_rejects_request_metric(tmp_path):
    extra = (
        "cooldown_s: 1\n"
        "slo: [ { metric: p99_ms, window: cooldown, lte: 100 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="resource-side time-sampled"):
        load_experiment(_write(tmp_path, extra))


def test_bad_slo_window_fails_fast(tmp_path):
    extra = (
        "slo: [ { metric: p99_ms, window: recovery, lte: 100 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="slo.window"):
        load_experiment(_write(tmp_path, extra))


def test_bad_slo_metric_fails_fast(tmp_path):
    extra = (
        "slo: [ { metric: latency, lt: 1 } ]\nload: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="slo.metric"):
        load_experiment(_write(tmp_path, extra))


def test_slo_needs_exactly_one_op(tmp_path):
    extra = "slo: [ { metric: p99_ms } ]\nload: { model: open, levels: [1], steady_s: 0.1 }\n"
    with pytest.raises(ValueError, match="exactly one"):
        load_experiment(_write(tmp_path, extra))


# ---- engine integration ----


def _exp(slo, *, abort=False) -> Experiment:
    return Experiment(
        subject=Subject("mock", Target(base_url="http://127.0.0.1:0")),
        workload=MockWorkload(base_ms=2),
        resources=[ResourceProfile()],
        loads=[
            LoadProfile(model="closed", schedule=Schedule.ramp_hold(lv, 0.0, 0.15)) for lv in (2, 4)
        ],
        slo=slo,
        abort_on_fail=abort,
    )


async def test_engine_run_passes_and_fails_on_slo():
    ok = await Engine(_exp([SloAssertion("p99_ms", "lt", 100000)])).run()
    assert ok.passed and len(ok.trials) == 2 and all(t.slo_passed for t in ok.trials)

    bad = await Engine(_exp([SloAssertion("p99_ms", "lt", 1)])).run()  # 1ms is unmeetable
    assert not bad.passed


async def test_engine_abort_on_fail_stops_sweep():
    run = await Engine(_exp([SloAssertion("p99_ms", "lt", 1)], abort=True)).run()
    assert not run.passed
    assert len(run.trials) == 1  # stopped after the first failing trial


# ---- CLI exit code (CI gate) ----


def test_cli_exit_code_reflects_slo(tmp_path):
    cfg = _write(
        tmp_path,
        "slo: [ { metric: p99_ms, lt: 1 } ]\nload: { model: closed, levels: [2], steady_s: 0.1 }\n",
    )
    assert main(["run", cfg, "--out", str(tmp_path / "runs"), "--mock"]) == 1
