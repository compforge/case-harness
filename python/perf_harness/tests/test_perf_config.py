import pytest

from perf_harness.config import load_experiment
from perf_harness.drive.workload import MockWorkload
from perf_harness.engine import Engine

_MIX = """
subject: { name: chat, base_url: "http://x:8001" }
resources: [ { workers: 2 } ]
workload: { name: mock }
facets: { difficulty: { values: [simple, complex], ordered: true } }
cases:
  - { id: a, weight: 70, facets: {difficulty: simple}, input: {ms: 3} }
  - { id: b, weight: 30, facets: {difficulty: complex}, input: {ms: 25} }
load: { model: closed, levels: [2, 4], ramp_s: 0, steady_s: 1 }
output_dir: /tmp/x
"""

_SINGLE = """
subject: { name: chat, base_url: "http://x" }
resources: [ {} ]
workload: { name: mock }
payload: { ms: 5 }
load: { model: closed, levels: [1], ramp_s: 0, steady_s: 0.5 }
"""

_BREAKER = """
subject: { name: chat, base_url: "http://x" }
resources: [ {} ]
workload: { name: mock }
load: { model: closed, levels: [2, 4], steady_s: 1, abort_on_error_rate: 0.1, breaker_min_n: 5 }
"""


def test_config_parses_circuit_breaker(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_BREAKER)
    exp, _ = load_experiment(str(cfg))
    # both load arms carry the mid-trial circuit-breaker config
    assert all(ld.abort_on_error_rate == 0.1 and ld.breaker_min_n == 5 for ld in exp.loads)
    assert all(ld.graceful_stop_s == 30.0 for ld in exp.loads)  # default drain window


@pytest.mark.parametrize(
    "bad",
    [
        "abort_on_error_rate: 0",  # would trip healthy traffic at min_n
        "abort_on_error_rate: 1.5",  # never trips
        "breaker_min_n: 0",  # no statistical floor
        "graceful_stop_s: -1",  # bypasses drain, not an explicit hard stop
    ],
)
def test_config_rejects_bad_stop_policy(tmp_path, bad):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "subject: { name: s, base_url: 'http://x' }\n"
        "resources: [ {} ]\nworkload: { name: mock }\n"
        f"load: {{ model: closed, levels: [1], steady_s: 0.1, {bad} }}\n"
    )
    with pytest.raises(ValueError):
        load_experiment(str(cfg))


def test_load_experiment_parses_cases_and_facets(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_MIX)
    experiment, out = load_experiment(str(cfg))

    assert out == "/tmp/x"
    assert experiment.name == "chat"  # config has no `name:` → subject slug
    assert experiment.workload.name == "mock"
    assert len(experiment.loads) == 2  # two levels
    assert {c.id for c in experiment.cases} == {"a", "b"}
    assert experiment.cases[0].facets == {"difficulty": "simple"}
    # weight rides the config ENTRY (experiment usage) — the Case object stays clean
    assert not hasattr(experiment.cases[0], "weight")
    assert experiment.mix.overrides == {"a": 70.0, "b": 30.0}
    assert experiment.facet_order == {"difficulty": ["simple", "complex"]}


def test_mix_resolves_to_engine_weights(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_MIX)
    experiment, _ = load_experiment(str(cfg))
    eng = Engine(experiment)
    # _weights are positional to experiment.cases (a, b); the mix sets both, no default needed
    assert eng._weights == [70.0, 30.0]


def test_load_experiment_backcompat_single_payload(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_SINGLE)
    experiment, _ = load_experiment(str(cfg))

    assert len(experiment.cases) == 1
    assert experiment.cases[0].id == "default"
    assert experiment.cases[0].input == {"ms": 5}
    assert experiment.facet_order == {}


_BASE = """
subject: { name: s, base_url: "http://x" }
resources: [ {} ]
workload: { name: mock }
"""


def _write(tmp_path, load_block: str):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_BASE + load_block)
    return str(cfg)


def test_invalid_model_fails_fast(tmp_path):
    with pytest.raises(ValueError, match="load.model"):
        load_experiment(_write(tmp_path, "load: { model: opn, levels: [1], steady_s: 0.1 }"))


def test_invalid_pacing_kind_fails_fast(tmp_path):
    with pytest.raises(ValueError, match="pacing.kind"):
        load_experiment(
            _write(
                tmp_path,
                "load: { model: closed, levels: [1], pacing: { kind: paced } }",
            )
        )


def test_stages_and_levels_mutually_exclusive(tmp_path):
    block = "load: { model: open, levels: [1], stages: [ { hold: 1, for_s: 1 } ] }"
    with pytest.raises(ValueError, match="not both"):
        load_experiment(_write(tmp_path, block))


def test_all_zero_weights_fail_fast(tmp_path):
    extra = (
        "cases:\n  - { id: a, weight: 0 }\n  - { id: b, weight: 0 }\n"
        "load: { model: closed, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="every case at 0"):
        load_experiment(_write(tmp_path, extra))


def test_top_level_mix_is_a_migration_error(tmp_path):
    # the old top-level mix: must point at inline weight, not silently parse
    extra = (
        "cases:\n  - { id: a }\nmix: { a: 2 }\n"
        "load: { model: closed, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="`weight:`"):
        load_experiment(_write(tmp_path, extra))


def test_slo_facet_label_typo_fails_fast(tmp_path):
    extra = (
        "cases:\n  - { id: a, facets: {difficulty: simple} }\n"
        "slo: [ { metric: 'p99_ms{difficulty=\"complx\"}', lt: 1 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="facet difficulty=complx unknown"):
        load_experiment(_write(tmp_path, extra))


def test_slo_stage_label_typo_fails_fast(tmp_path):
    extra = (
        "slo: [ { metric: 'p99_ms{stage=\"hold@99\"}', lt: 1 } ]\n"
        "load:\n  model: open\n  stages:\n"
        "    - { hold: 10, for_s: 0.1 }\n    - { hold: 20, for_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="stage 'hold@99' unknown"):
        load_experiment(_write(tmp_path, extra))


def test_slo_legacy_scope_key_rejected(tmp_path):
    extra = (
        'slo: [ { metric: p99_ms, lt: 1, scope: "overall" } ]\n'
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="slo.scope was removed"):
        load_experiment(_write(tmp_path, extra))


_UNREGISTERED = """
subject: { name: s, base_url: "http://x" }
resources: [ {} ]
workload: { name: chat }
load: { model: closed, levels: [1], steady_s: 0.1 }
"""


def test_mock_bypasses_unregistered_workload(tmp_path):
    cfg = tmp_path / "u.yaml"
    cfg.write_text(_UNREGISTERED)
    with pytest.raises(ValueError, match="unknown workload"):
        load_experiment(str(cfg))  # real path needs `chat` registered
    exp, _ = load_experiment(str(cfg), mock=True)  # mock skips the registry
    assert isinstance(exp.workload, MockWorkload)


def test_slo_multi_facet_label_rejected(tmp_path):
    # marginal pivot, not a cube → at most one facet/stage slice label
    extra = (
        "cases:\n  - { id: a, facets: {difficulty: simple, lang: zh} }\n"
        'slo: [ { metric: \'p99_ms{difficulty="simple",lang="zh"}\', lt: 1 } ]\n'
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="at most one facet/stage"):
        load_experiment(_write(tmp_path, extra))


def test_slo_undeclared_per_request_metric_rejected(tmp_path):
    # a dynamic first_<event>_ms reaches the report but cannot gate (fail-fast)
    extra = (
        "slo: [ { metric: first_answer_ms.p95, lt: 1 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    with pytest.raises(ValueError, match="not a declared metric"):
        load_experiment(_write(tmp_path, extra))


def test_slo_framework_ttft_is_declared(tmp_path):
    extra = (
        "slo: [ { metric: ttft_ms.p95, lt: 2000 } ]\n"
        "load: { model: open, levels: [1], steady_s: 0.1 }\n"
    )
    exp, _ = load_experiment(_write(tmp_path, extra))  # ttft_ms is framework-declared
    assert exp.slo[0].metric == "ttft_ms.p95"
