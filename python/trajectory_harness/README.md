# trajectory_harness

Normalize agent recordings, evaluate their decisions, aggregate dataset-level metrics,
and render comparable trajectory reports.

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
  -> EvaluationResult (verdict + measurements)
  -> EvaluationRun
  -> Metric
  -> Report / HTML
```

The bundled loader accepts OTLP JSON, Tempo's OTLP wrapper, and flat OTLP JSONL. Message
payloads follow the OTel GenAI `role + parts` schema. A failed operation carries a
normalized `Failure(kind, phase, error_type)`; for example `llm.request.timeout` or
`tool.prepare.dependency_missing`.

Common evaluators ship with the Harness. Domain evaluators use the same contract and set
`EvaluatorSpec.kind="domain"` plus their owner. Evaluators produce per-trajectory
measurements; `aggregate_metrics` turns execution facts, failures, and those measurements
into dataset-level metrics. It does not manufacture a weighted overall score.

`trajectory_harness` owns the trajectory-specific report sections and HTML entry point.
Report functions can aggregate full runs or accept persisted `Metric` values for historical
trends. Trend time comes from `EvaluationRun.created_at`; `run_id` is only an opaque identity,
so callers may schedule runs weekly, per release, or on demand. The final low-level document
rendering remains in `harness_common.report_kit`, so consumers can append business-specific
`Section` values without writing HTML.

See [`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md) for the model and
its boundary with eval/trace analysis.
