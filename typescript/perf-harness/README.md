# @compforge/perf-harness

TypeScript implementation of the repository's language-neutral Perf Harness contract. It runs
open- or closed-loop load profiles, preserves per-request outcomes and correlation IDs, and emits
the shared model/raw artifacts described by `spec/perf-contract.md`.

```ts
import { Engine, rampHold, writeRunData, type Workload } from "@compforge/perf-harness";

const workload: Workload = {
  fire: async ({ signal }) => {
    const started = performance.now();
    const response = await fetch("http://service/api/run", { method: "POST", signal });
    return { status: response.status, duration_ms: performance.now() - started };
  },
};

const run = await new Engine({
  name: "service-capacity",
  subject: { name: "service", target: {} },
  workload,
  caseMix: [
    { case: { id: "ordinary_chat", input: { query: "hello" } }, weight: 4 },
    { case: { id: "knowledge_chat", input: { query: "use the docs" } }, weight: 1 },
  ],
  resources: [{}],
  loads: [rampHold("closed", 20, 10, 60)],
}).run();

writeRunData(run, "./runs/service-capacity");
```

`caseMix` selects one or more canonical Case assets for this Experiment; its weights are load-plan
metadata and do not mutate the Cases. `CaseView` is only the minimal runtime shape accepted by the
Harness—the canonical Case/CaseSet schema remains owned by spec-case.

Service-specific request and SSE semantics stay in the consumer's `Workload`. Each `fire` handles
exactly one dispatch and must be safe for concurrent calls; the Workload must not start its own load
loop. Resource-side
Prometheus/Kubernetes observation stays with the consumer as well; Doctor, for example, reuses its
existing Prombed-backed `doctor metric` collection.

`writeRunData` writes the shared `run.json`, `outcomes.jsonl`, and `verdict.json` artifacts. The
implementation supports open/closed load, ramp/hold schedules, closed-loop pacing, request/inflight
safety limits and an error-rate breaker. Resource probes and rendered reports remain consumer-owned.
Until the
TypeScript API exposes SLO checks, a normally completed run has verdict status `skipped`: it was observed,
not judged. Error-rate or abort stops produce a failing verdict.
