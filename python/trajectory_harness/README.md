# trajectory_harness

Normalize agent recordings into one ordered trajectory and evaluate the decisions and
actions inside it.

```python
from trajectory_harness import OTelJsonLoader, RepeatedToolCallEvaluator, evaluate

trajectory = OTelJsonLoader().load("trace.json")[0]
report = evaluate(trajectory, [RepeatedToolCallEvaluator()])
print(report.to_dict())
```

The bundled loader accepts OTLP JSON, Tempo's OTLP wrapper, and flat OTLP JSONL. Message
payloads follow the OTel GenAI `role + parts` schema. Add another recording format by
implementing `TrajectoryLoader`; add another judgment by implementing `Evaluator`.

See [`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md) for the model and
its boundary with eval/trace analysis.
