# Example: Agent eval (EvalEngine + AsyncSSERunner + BaseLLMJudge)

Minimal demo of the dataset-driven evaluation flow.

## Layout

```
agent-test/
├── config.yaml            # service base_url + auth + judge env vars (in custom)
├── pipelines/
│   └── smoke.yaml         # one corpus + one cases file + selected metrics
├── corpora/
│   └── rag_basics/
│       ├── manifest.yaml  # which docs to upload + selected flag
│       └── docs/*.md
├── cases/
│   └── rag_qa.yaml        # list of EvalCase rows (id, question, expected_answer)
├── biz/
│   ├── client.py          # service-specific HTTP client (uses AsyncJSONRunner / AsyncSSERunner)
│   ├── prepare.py         # MyPrepareHandler(BasePrepareHandler)
│   ├── chat_runner.py     # ChatRunner(BaseEvalRunner) — trigger one case via SSE
│   └── chat_builder.py    # ChatBuilder(BaseDatasetBuilder) — message → EvalSample
├── metrics/
│   ├── correctness.py     # CorrectnessJudge(BaseLLMJudge) + module-level NAME/score
│   └── refusal.py         # sync RefusalMetric stub
├── pyproject.toml
└── engine.py              # CLI entry: load pipeline, build context, run EvalEngine
```

## How it ties together

```python
# engine.py — sketch
import asyncio
from e2e_harness.eval import EvalContext, EvalEngine, MetricRegistry
from biz.prepare import WidgetPrepareHandler
from biz.chat_runner import ChatRunner
from biz.chat_builder import ChatBuilder

async def main():
    ctx = EvalContext(pipeline=..., corpus=..., cases=..., runtime=..., started_at=...)
    engine = EvalEngine(
        ctx,
        prepare_fn=WidgetPrepareHandler(),
        runner_factory=lambda biz: ChatRunner,
        builder_factory=lambda biz: ChatBuilder,
        metric_registry=MetricRegistry("metrics"),
    )
    await engine.run()

asyncio.run(main())
```

Each business primitive is ~30 lines of subclass code; framework handles loop,
error isolation, artifact persistence, scoring, CSV/MD reporting.

See `biz/chat_runner.py` and `metrics/correctness.py` for the smallest concrete
patterns.
