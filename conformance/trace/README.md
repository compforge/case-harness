# Trace Harness conformance fixtures

Python and TypeScript MUST consume the same files in this directory.

- `fixtures/genai-basic.jsonl` is the raw Jaeger-span input.
- `cases/genai-basic.analysis.json` is the exact canonical Analysis IR after generic GenAI
  assembly and diagnosis.

Implementation-specific tests additionally verify that one `TraceHarness` instance cannot see
another instance's contributed features, detectors, facets, or lazy features.
