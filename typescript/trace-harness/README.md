# @compforge/trace-harness

TypeScript implementation of this repository's Python `trace_harness` core. It consumes Jaeger
span documents, fuses physical spans into logical nodes, derives facts and findings, and renders
a self-contained interactive node-tree HTML report.

```ts
import {
  assemble,
  diagnose,
  genAiSpecs,
  normalizeJaegerSpans,
  renderInteractive,
} from "@compforge/trace-harness";

const spans = normalizeJaegerSpans(rawJaegerDocuments);
const context = assemble(spans, genAiSpecs());
const html = renderInteractive(context, diagnose(context));
```

Domain-specific kinds, features and facets stay in the consumer and compose with the generic
implementation through `mergeSpecs`, `registerFeature` and `registerFacet`.
