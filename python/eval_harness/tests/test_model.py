import pytest
from harness_common.case import Case
from pydantic import ValidationError

from eval_harness.model.evalset import (
    BASE_FACETS,
    EvalSet,
    FacetSchema,
    FacetSpec,
    eval_view,
)
from eval_harness.model.experiment import Env, Experiment, Target, expand_matrix
from eval_harness.model.sample import MetricResult
from eval_harness.tests.eval_cases import make_eval_case


def test_metric_result_channel():
    assert MetricResult("correctness", "score", score=0.8).channel == "quality"
    assert MetricResult("latency", "measure", value=1200, unit="ms").channel == "measurement"
    rt = MetricResult.from_dict(MetricResult("x", "binary", score=1.0, judgement="hi").to_dict())
    assert rt.score == 1.0 and rt.judgement == "hi" and rt.kind == "binary"


def test_eval_view_contract():
    # eval's read of a canonical case enforces eval's contract (the schema is common.Case;
    # the per-face rules live in eval_view, not the case model).
    eval_view(make_eval_case(id="a", expected_behavior="answer", ground_truth="42"))
    with pytest.raises(ValueError, match="refuse"):  # refuse case must not carry ground_truth
        eval_view(
            Case(
                id="b",
                input={"query": "q"},
                judge={"eval": {"expected_behavior": "refuse", "ground_truth": "nope"}},
            )
        )
    with pytest.raises(ValueError, match="query"):  # no stimulus → not an eval case
        eval_view(Case(id="c", input={}))


def test_facet_schema_validation():
    schema = FacetSchema(
        {
            "type": FacetSpec(values=["factual", "summary"]),
            "domain": FacetSpec(open=True),
        },
        base=BASE_FACETS,
    )
    # base difficulty inherited + ordered
    schema.validate_dimensions(
        "c1", {"difficulty": "hard", "type": "summary", "domain": "anything"}
    )
    with pytest.raises(ValueError):  # unknown facet key
        schema.validate_dimensions("c2", {"topic": "x"})
    with pytest.raises(ValueError):  # constrained value out of vocab
        schema.validate_dimensions("c3", {"difficulty": "trivial"})
    # ordered facet sorts by declared order, not alpha
    assert schema.order_key("difficulty", "easy") < schema.order_key("difficulty", "hard")


def test_facet_spec_requires_values_or_open():
    with pytest.raises(ValidationError):
        FacetSpec()


def _target(tenant="t1"):
    return Target(name="chat", config={"tenant_id": tenant, "host": {"base_url": "http://x"}})


# which config paths re-provision (the consumer declares these per experiment)
_HEAVY = ["config.tenant_id"]


def test_env_resolve_and_dotted_override():
    env = Env(
        name="e",
        overrides={
            "config.params.target_searches": 6,
            "config.host.base_url": "http://y",
        },
    )
    r = env.resolve(_target())
    assert r.config["params"]["target_searches"] == 6
    assert r.config["host"]["base_url"] == "http://y"
    assert r.config["tenant_id"] == "t1"


def test_env_key_light_vs_heavy():
    t = _target()
    base = Env(name="base", overrides={})
    light = Env(name="light", overrides={"llm.model": "model-beta"})  # light → same key
    heavy = Env(name="heavy", overrides={"config.tenant_id": "t2"})  # heavy → different key
    assert base.key("rag", t, _HEAVY) == light.key("rag", t, _HEAVY)
    assert base.key("rag", t, _HEAVY) != heavy.key("rag", t, _HEAVY)
    assert base.key("rag", t, _HEAVY) != base.key("other_corpus", t, _HEAVY)  # corpus is heavy


def test_expand_matrix():
    envs = expand_matrix({"config.params.target_searches": [3, 6], "config.tenant_id": ["a", "b"]})
    assert len(envs) == 4
    names = {e.name for e in envs}
    assert "target_searches=3__tenant_id=a" in names


def _exp(envs=None, matrix=None):
    return Experiment(
        name="exp",
        target=_target(),
        evalsets=[
            EvalSet(
                corpus="rag",
                cases=[make_eval_case(id="q1", query="q", ground_truth="a")],
            )
        ],
        envs=envs or [],
        matrix=matrix or {},
        metrics=["correctness"],
        weights={"correctness": 1.0},
    )


def test_resolved_envs_defaults_to_one():
    envs = _exp().resolved_envs()
    assert len(envs) == 1 and envs[0].name == "default" and envs[0].overrides == {}


def test_experiment_hash_stable_and_sensitive():
    e1 = _exp(envs=[Env(name="a"), Env(name="b")])
    e2 = _exp(envs=[Env(name="b"), Env(name="a")])  # order-independent
    assert e1.experiment_hash() == e2.experiment_hash()
    e3 = _exp(envs=[Env(name="a"), Env(name="c")])  # different env set
    assert e1.experiment_hash() != e3.experiment_hash()
