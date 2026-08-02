# case-harness

> **Cases in, verdicts out.** A cross-language family of test harnesses that splits "is the system robust?" into separately-answerable questions — API correctness (e2e), agent quality (eval), capacity under pressure (perf), in-trace attribution (trace), and agent trajectory quality — all driven by the same reusable **case** assets. Sibling of [spec-case](https://github.com/qiankunli/spec-case) (the asset format) and [case-code-review](https://github.com/qiankunli/case-code-review) (the white-box consumer). ｜ 中文: [README.zh-CN.md](./README.zh-CN.md)

## Why this repo exists

An AI project keeps growing — more features, longer chains, a wider test surface. Problems tend to surface right before a release, get patched in a hurry, and even then nobody dares to say the system is truly fine. This repo's answer: split "is the system robust?" into questions you can answer separately, and build one harness per question — the first three are **black-box testing** (send requests, watch responses), while trace and trajectory are complementary **open-box analyses**:

| Question | Kind | SDK |
|----------|------|-----|
| Are the APIs correct? | API testing (e2e, black-box) | `python/e2e_harness` |
| Is the agent any good? | Quality evaluation (eval, black-box) | `python/eval_harness` |
| How does it behave under pressure? | Load testing (perf, black-box) | `python/perf_harness` |
| Which layer misbehaves first? | Trace analysis (trace, open-box) | `python/trace_harness` |
| Were the agent's decisions and actions efficient? | Trajectory evaluation (open-box) | `python/trajectory_harness` |

This repo ships SDKs, not tests: the system under test (SUT) integrates the SDK in its own repo, organized around its own protocol / auth / resource lifecycle.

## Core ideas

1. **Different judgments, one case format.** A case only describes "how to exercise the system once" — never how to judge it. The same case drives e2e (correctness), eval (quality) and perf (capacity). Consistency lives in the data format under `spec/`, not in shared code.
2. **Cases are accumulating assets.** Decoupled from judgment, cases keep piling up; the more you have, the more a full pre-release run actually means something.
3. **One experiment = one config yaml; artifacts land per run.** Results go to `runs/<scope>/<run-id>/`; recording is separated from rendering, runs accumulate instead of overwriting, and reports can aggregate across runs.
4. **One execution, many observations.** A single request can feed correctness (e2e), quality (eval), latency/resources (perf), in-chain attribution (trace), and decision-path evaluation (trajectory). The harnesses are viewpoints, not separate load generators.

The unified output is `verdict.json` (schema: [`spec/verdict-schema.yaml`](spec/verdict-schema.yaml)): humans read it, CI reads it, and agentic dev loops read it to self-correct.

## Division of labor with spec-case

[spec-case](https://github.com/qiankunli/spec-case) is the **asset layer**: `@spec`/`@case`/`@rule` markers live on the code, distilled by per-language tools into machine-readable assets bound to code via symbol-id; it also ships the canonical `Case` model (`spec_case.model`). case-harness is the **runtime layer**: it runs those cases black-box into verdicts. The same assets' white-box consumer is [case-code-review](https://github.com/qiankunli/case-code-review), which attaches spec/case to review units as a checklist.

## Layout

```
case-harness/
├── spec/                # language-neutral conventions: case-schema / verdict-schema / conventions
├── python/              # Python workspace (uv), five sibling SDKs + shared harness_common
│   ├── e2e_harness/     # API testing: deterministic contract tests, judgment-as-data, pytest-driven
│   ├── eval_harness/    # quality evaluation: experiment/Env arms + Worksheet + reconciler
│   ├── perf_harness/    # load testing: capacity/resource profiling under constraints
│   ├── trace_harness/   # trace analysis: OTel/Jaeger span attribution, call stacks + findings + corpus
│   ├── trajectory_harness/ # agent trajectory normalization + evaluation
│   └── harness_common/  # neutral shared layer: verdict / llm / report_kit
├── go/                  # Go SDK (reference implementation, shapes aligned to spec/)
├── examples/            # integration examples: api-test / agent-test
└── docs/                # cross-SDK design docs
```

The five Python SDKs share one uv workspace and the `spec/` conventions but **never import each other**; genuinely common code lives in `harness_common`.

## Quickstart

```bash
# Python: the five SDKs share one uv workspace
cd python && uv sync && uv run pytest -q

# eval_harness end-to-end (mock, no live services)
uv run python -m eval_harness.cli eval_harness/materials/experiments/smoke.yaml --mock --fresh --runs-dir /tmp/ch

# perf_harness end-to-end (mock)
uv run python -m perf_harness.cli run perf_harness/examples/mock.yaml --out /tmp/ph

# trace analysis (offline jaeger file → call stacks + findings)
uv run trace single trace_harness/tests/fixtures/trace_genai_sample.jsonl --diagnose

# Go (reference implementation)
cd go && go test ./...
```

Per-SDK integration guides live in each SDK's `README.md`; developer-facing code maps and conventions in each `AGENTS.md`.

## Status

Early public release. The case/verdict schemas under `spec/` are the stable center; SDK APIs may still move. The Go SDK tracks the Python side batch-wise.
