# case-harness

> **Cases in, verdicts out.** Reusable cases go in; e2e, eval, perf, trace, and trajectory runs produce one machine-readable Verdict. 中文版见 [README.zh-CN.md](./README.zh-CN.md).

## What it is

case-harness is a cross-language family of testing SDKs for projects whose quality can no longer be answered by one test command. It separates API correctness, agent quality, capacity, trace attribution, and agent trajectory into distinct judgment views while letting them reuse the same versioned Case assets.

The repository provides harness SDKs and platform tools, not a test suite for your product. The system under test keeps its own cases, protocol adapters, credentials, resource lifecycle, and acceptance criteria.

## What it assesses

| Question | View | Available SDKs |
|---|---|---|
| Do public APIs still behave correctly? | e2e | Python / Go |
| Is an agent's output good enough? | eval | Python |
| What happens under declared load and resource constraints? | perf | Python / TypeScript |
| Which layer in a physical call chain became abnormal first? | trace | Python / TypeScript |
| Were an agent's decisions and actions reasonable? | trajectory | Python |

The first three views judge the system from public behavior; trace and trajectory inspect execution evidence. “Black-box” describes the judgment boundary, not every setup action: preparing an environment, injecting a controlled failure, or observing resource pressure may still require deployment-level tools.

Current e2e targets a single service's public boundary. Product-level Web, mobile, and multi-service functional testing remain a longer-term scope rather than being conflated with service API contracts.

## How it works

```text
canonical CaseSet owned by the project
    + execution / collection
    → Observation
    → Unit (Case + Observation + Annotation)
    → versioned Dataset

Dataset + Evaluators / Measurers / optional Policy
    → EvaluationRun
    → Worksheet (Unit + Evaluation + Measurement)
    → Metric / Verdict / Report (JSON / HTML)
```

| Concept | Meaning |
|---|---|
| **Case** | Stable, reusable test input and judgment data, identified by `case_id`; the canonical format is owned by [spec-case](https://github.com/compforge/spec-case). |
| **Observation** | What actually happened when a Case ran: an outcome, response, performance sample, trace, or trajectory with source identity. |
| **Unit** | A harness-defined evaluation unit sourced from a Case and one or more Observations; one Worksheet row represents one Unit. |
| **Annotation** | Human, external-system, or model supervision that exists before the current evaluation, such as a label, reference, or review conclusion. |
| **Dataset** | A versioned, reusable collection of Unit facts and existing Annotations. It does not contain results from one particular EvaluationRun. |
| **EvaluationRun** | One configured application of Evaluators, Measurers, and an optional Policy to a fixed Dataset version. |
| **Evaluation** | A Judge or Evaluator's quality conclusion about a Unit, such as a verdict, score, explanation, or Finding. |
| **Measurement** | A factual value extracted from a Unit, such as tokens, latency, calls, or resource usage, without a quality verdict. |
| **Worksheet** | One EvaluationRun's row-wise result over a Dataset, with Evaluation and Measurement cells added to each Unit. |
| **Run** | The artifact and lifecycle boundary for one real execution, carrying environment and alignment identity. |
| **Report** | A machine-facing JSON or human-facing HTML projection of a Worksheet. |
| **Verdict** | The common machine-readable result consumed by humans, CI, and agent development loops. |

A Case can be viewed from more than one angle. When one execution already produced responses, performance samples, traces, or a trajectory, those observations form a reusable Dataset. Selecting different Evaluators, Measurers, or Policies then produces new EvaluationRuns, Worksheets, and reports without triggering duplicate execution.

## Shared platform toolbox

Some execution mechanics serve more than one harness. Recovery E2E and performance tests, for example, both need reliable Kubernetes workload discovery, state convergence, and Event evidence. The Go `kube` package provides namespace-scoped Kubernetes control and observation without owning any business Case, load profile, or Verdict.

The consuming project still decides which workload to target, when a disruption is allowed, and what proves recovery or acceptable performance. Additional fault-injection backends can join this toolbox without moving experiment intent out of the project. See the [Harness toolbox](docs/toolbox.md) for its boundary and current capabilities.

## Get started

Choose the example closest to your test:

| Example | Use it for |
|---|---|
| [`examples/api-test`](examples/api-test/README.md) | Small data-driven API cases |
| [`examples/python-service`](examples/python-service/) | Python CaseRun with setup and cleanup |
| [`examples/go-service`](examples/go-service/) | Go CaseRun, `go test` aggregation, and Verdict output |
| [`examples/agent-test`](examples/agent-test/README.md) | Dataset-driven agent evaluation |

Run the Python API example from a source checkout:

```bash
cd python
uv sync
export WIDGET_TOKEN=...
uv run e2e run ../examples/api-test/cases.yaml \
  --config ../examples/api-test/config.yaml \
  --runs-dir ../runs
```

Run the Go service example against a deployed service:

```bash
cd examples/go-service
export ASANDBOX_BASE_URL=http://localhost:8090
export EXAMPLE_TOKEN=...
go test -tags=e2e -v ./...
```

Both paths write a Run directory ending in `verdict.json`. Skipped or errored cases remain visible and are not interpreted as successful verification.

## Ownership

| Owner | Responsibility |
|---|---|
| Project under test | Versioned Case assets, test code, domain actions, acceptance criteria |
| case-harness | Execution mechanisms, domain Harnesses, Run artifacts, reporting infrastructure, Verdict contracts, shared platform tools |
| spec-case | Canonical Case model and code-to-Case intent markers |
| Deployment workflow | Environment, credentials, target revision, trigger policy, and release gates |

This split keeps test intent close to the product while allowing execution mechanics and output contracts to improve centrally. [case-code-review](https://github.com/compforge/case-code-review) consumes the same assets from a white-box review perspective.

## SDK map

| Path | Capability |
|---|---|
| `python/e2e_harness` / `go/e2e` | Deterministic CaseRun execution and API assertions |
| `python/eval_harness` | Agent evaluation and comparative experiments |
| `python/perf_harness` / `typescript/perf-harness` | Load generation, SLOs, and capacity evidence |
| `python/trace_harness` / `typescript/trace-harness` | Trace normalization, attribution, and findings |
| `python/trajectory_harness` | Agent trajectory normalization and evaluation |
| `go/kube` | Kubernetes control and observation shared by e2e and perf |

## Repository development

```bash
cd python && uv sync && uv run pytest -q
cd ../go && go test ./...
cd ../typescript/trace-harness && bun install --frozen-lockfile && bun test
cd ../perf-harness && bun install --frozen-lockfile && bun test
```

## Status

case-harness is an early public project. The canonical Case schema comes from spec-case; the Verdict and runtime contracts under `spec/` are its stable center. Language SDKs may cover different features while continuing to share those contracts.
