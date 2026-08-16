# trajectory_harness

Normalize agent and workflow recordings, evaluate their decisions, aggregate dataset-level
metrics, and render comparable trajectory reports.

```python
from datetime import datetime, timezone

from trajectory_harness import (
    DatasetRef,
    EvaluationRun,
    ExecutionSuccessEvaluator,
    OTelJsonLoader,
    RepeatedToolCallEvaluator,
    aggregate_metrics,
    evaluate,
    write_report_html,
)

evaluators = (ExecutionSuccessEvaluator(), RepeatedToolCallEvaluator())
trajectories = OTelJsonLoader().load("trace.json")
items = tuple(evaluate(trajectory, evaluators) for trajectory in trajectories)
run = EvaluationRun(
    run_id="evaluation-001",
    created_at=datetime.now(timezone.utc),
    dataset=DatasetRef("reviews", slice="unit", sample_count=len(items)),
    items=items,
    evaluator_specs=tuple(evaluator.spec for evaluator in evaluators),
)

print([metric.to_dict() for metric in aggregate_metrics(run)])
write_report_html("trajectory-report.html", [run])
```

The processing boundary is:

```text
Source
  -> TrajectoryLoader
  -> Trajectory (Step + Failure + ExecutionResult)
  -> Evaluator
  -> EvaluationResult (verdict + measurements + signals)
  -> EvaluationRun
  -> Metric
  -> Report / HTML
```

The bundled loader accepts OTLP JSON, Tempo's OTLP wrapper, and flat OTLP JSONL. Message
payloads follow the OTel GenAI `role + parts` schema. A failed operation carries a
normalized `Failure(kind, phase, error_type)`; for example `llm.request.timeout` or
`tool.prepare.dependency_missing`.

A trajectory may contain one agent loop or a pipeline of several agent loops and deterministic
operations. `Step.parent_step_id` preserves that execution hierarchy; domain evaluators select
the relevant subtrees through step `operation`, `name`, and `attributes`. The common model does
not introduce a separate stage abstraction.

Recurring LLM failures use the shared `llm_failure(phase, error_type)` constructor.
Its common phases are `routing`, `request`, and `response_parse`; common error types
include `timeout`, `rate_limit`, `client_error`, `server_error`, `network_error`,
`invalid_response`, and `unknown`. Loaders still own source-specific parsing and may
use open strings for domain-specific tool, agent, and workflow failures.

Common evaluators ship with the Harness. Domain evaluators use the same contract and set
`EvaluatorSpec.kind="domain"` plus their owner. Evaluators produce per-trajectory
measurements; `aggregate_metrics` turns execution facts, failures, and those measurements
into dataset-level metrics. It does not manufacture a weighted overall score.
Optimization patterns are signals, not execution failures: for example, exact repeated tool
calls produce a `warning`, a repeat-rate measurement, and a `DiagnosticSignal`. The signal
records the observed pattern and evidence separately from hypotheses such as missing batching,
unclear tool guidance, or an ineffective repeat-call stopping strategy.
Evaluator verdicts remain separate from runtime `Failure`: a domain rule may return
`verdict="fail"`, while `status="error"` is reserved for an evaluator that could not run.

The common evaluator catalog grows around reusable signals from the three parts of an agent
loop: system prompt behavior, tool-set use, and loop mechanisms such as context and stopping.
This mapping is diagnostic rather than causal: one signal may point to several design surfaces,
while business-specific contracts and cross-loop pipeline judgments remain domain evaluators.
The HTML report keeps low-cardinality failure metrics and lists the affected trajectory IDs,
so consumers can correlate failures with case attributes without turning case IDs into metric
dimensions.

`trajectory_harness` owns the trajectory-specific report sections and HTML entry point.
Report functions can aggregate full runs or accept persisted `Metric` values for historical
trends. Trend time comes from `EvaluationRun.created_at`; `run_id` is only an opaque identity,
so callers may schedule runs weekly, per release, or on demand. The final low-level document
rendering remains in `harness_common.report_kit`, so consumers can append business-specific
`Section` values without writing HTML.

See [`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md) for the model and
its boundary with eval/trace analysis.
