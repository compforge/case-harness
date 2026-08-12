# case-harness

> **Cases in, verdicts out.** A cross-language family of test harnesses that splits "is the system robust?" into separately-answerable questions — API correctness (e2e), agent quality (eval), capacity under pressure (perf), in-trace attribution (trace), and agent trajectory quality — all driven by the same reusable **case** assets. Sibling of [spec-case](https://github.com/compforge/spec-case) (the asset format) and [case-code-review](https://github.com/compforge/case-code-review) (the white-box consumer). ｜ 中文: [README.zh-CN.md](./README.zh-CN.md)

## Why this repo exists

An AI project keeps growing — more features, longer chains, a wider test surface. Problems tend to surface right before a release, get patched in a hurry, and even then nobody dares to say the system is truly fine. This repo's answer: split "is the system robust?" into questions you can answer separately, and build one harness per question — the first three are **black-box testing** (send requests, watch responses), while trace and trajectory are complementary **open-box analyses**:

| Question | Kind | SDK |
|----------|------|-----|
| Are the APIs correct? | API testing (e2e, black-box) | `python/e2e_harness` |
| Is the agent any good? | Quality evaluation (eval, black-box) | `python/eval_harness` |
| How does it behave under pressure? | Load testing (perf, black-box) | `python/perf_harness` / `typescript/perf-harness` |
| Which layer misbehaves first? | Trace analysis (trace, open-box) | `python/trace_harness` / `typescript/trace-harness` |
| Were the agent's decisions and actions efficient? | Trajectory evaluation (open-box) | `python/trajectory_harness` |

This repo ships SDKs, not tests: the system under test (SUT) integrates the SDK in its own repo, organized around its own protocol / auth / resource lifecycle.

### Where it sits in the testing stack

Product positioning is usually more stable than requirements, and requirements and public contracts are more stable than implementation code. That gives three distinct testing boundaries:

| Level | Boundary | Purpose | Status |
|---|---|---|---|
| Web / app functional testing | UI or product entry point, potentially spanning services | Verify a complete user journey, including client code | Long-term scope; not implemented yet |
| API functional testing | Product entry APIs, potentially multi-step and cross-service | Verify backend product behavior without exercising client code | Long-term scope; not implemented yet |
| Service API contract testing | One service's public API | Verify that its contract still works after refactoring | Current `e2e_harness` |
| Unit testing | Function, class, or module | Verify local implementation; evolves most frequently with code | Owned by the SUT repo |

Here, `e2e` means end-to-end **relative to one service SUT boundary**, not product-level UI E2E. Long-term functional testing starts from a natural-language Playbook, compiles reviewed Web / Android / iOS / API Scripts at authoring time, and executes them through target-specific SDKs. See [`docs/kernel.md`](docs/kernel.md) for the full model.

## Core ideas

1. **Different judgments, one case format.** A case carries one reusable stimulus plus face-specific judgment data (`judge.e2e/eval/perf`). Environment, lifecycle code and experiment parameters stay outside it. `spec-case` owns the canonical asset format and model.
2. **Cases are accumulating assets.** Decoupled from judgment, cases keep piling up; the more you have, the more a full pre-release run actually means something.
3. **Experiments compare Arms through Trials.** An Experiment asks one question, an Arm is one named configuration in the comparison, and a Trial is one real execution of an Arm. Results go to `runs/<scope>/<run-id>/`; `arm_id` stays an explicit alignment key across artifacts.
4. **One execution, many observations.** A single request can feed correctness (e2e), quality (eval), latency/resources (perf), in-chain attribution (trace), and decision-path evaluation (trajectory). The harnesses are viewpoints, not separate load generators.
5. **Cases anchor stable contracts.** Case identity and assertion meaning come from requirements or public API contracts. Co-locating a marker with a handler enables discovery and drift detection; it does not make an internal function name or file path the case's business identity.
6. **Long cases have an explicit lifecycle.** CaseRun separates prepare, execute, judge and cleanup; each phase has a budget, cleanup always runs, and cleanup failure is an error rather than hidden best-effort noise.

The unified output is `verdict.json` (schema: [`spec/verdict-schema.yaml`](spec/verdict-schema.yaml)): humans read it, CI reads it, and agentic dev loops read it to self-correct.

## Division of labor with spec-case

[spec-case](https://github.com/compforge/spec-case) is the **asset layer**: `@spec`/`@case`/`@rule` markers live on the code, distilled by per-language tools into machine-readable assets bound to code via symbol-id; it also ships the canonical `Case` model (`spec_case.model`). case-harness is the **runtime layer**: it runs those cases black-box into verdicts. The same assets' white-box consumer is [case-code-review](https://github.com/compforge/case-code-review), which attaches spec/case to review units as a checklist.

## Layout

```
case-harness/
├── spec/                # runtime conventions: case compatibility projection / verdict / config
├── python/              # Python workspace (uv), five sibling SDKs + shared harness_common
│   ├── e2e_harness/     # API testing: deterministic contract tests, judgment-as-data, pytest-driven
│   ├── eval_harness/    # quality evaluation: Experiment/Arm comparison + Worksheet + reconciler
│   ├── perf_harness/    # load testing: capacity/resource profiling under constraints
│   ├── trace_harness/   # trace analysis: OTel/Jaeger span attribution, call stacks + findings + corpus
│   ├── trajectory_harness/ # agent trajectory normalization + evaluation
│   └── harness_common/  # neutral shared layer: verdict / llm / report_kit
├── go/                  # Go SDK (reference implementation, shapes aligned to spec/)
├── typescript/          # TypeScript perf/trace SDKs implementing contracts under spec/
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
uv run trace single ../conformance/trace/fixtures/genai-basic.jsonl --diagnose

# Go (same CaseRun/Verdict semantics, idiomatic API)
cd go && go test ./...

# TypeScript trace-harness
cd typescript/trace-harness && bun install --frozen-lockfile && bun test

# TypeScript perf-harness
cd ../perf-harness && bun install --frozen-lockfile && bun test
```

Per-SDK integration guides live in each SDK's `README.md`; developer-facing code maps and conventions in each `AGENTS.md`.

## Status

Early public release. The canonical case schema comes from `spec-case`; verdict and runtime contracts under `spec/` are this repo's stable center. SDK APIs may still move. Language implementations may cover different features, but their shared IR follows the same contracts rather than treating one implementation as canonical.
