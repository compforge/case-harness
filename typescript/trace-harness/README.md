# @compforge/trace-harness

TypeScript implementation of this repository's Python `trace_harness` core. It consumes Jaeger
span documents, fuses physical spans into logical nodes, derives facts and findings, and renders
a self-contained interactive node-tree HTML report.

```ts
import {
  genAiSpecs,
  normalizeJaegerSpans,
  TraceHarness,
} from "@compforge/trace-harness";

const spans = normalizeJaegerSpans(rawJaegerDocuments);
const harness = new TraceHarness({ specs: genAiSpecs() });
const context = harness.assemble(spans);
const html = harness.renderInteractive(context, harness.diagnose(context));
```

Domain-specific behavior stays in the consumer and is passed explicitly as scoped
`TraceContributions` (`specs`, `features`, `detectors`, and declarative `facets`). Facets state
presentation intent; the harness owns traversal and serialization. The language-neutral contract
is [`spec/trace-harness.md`](../../spec/trace-harness.md).
