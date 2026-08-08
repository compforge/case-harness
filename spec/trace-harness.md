# Trace Harness 1.0

## 1. Scope

Trace Harness defines a language-neutral pipeline for turning raw distributed-trace spans into
logical analysis nodes, findings, and presentation trees. Python and TypeScript are peer
implementations of this specification. Neither implementation is the specification.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** describe normative
requirements.

Collection, environment discovery, credentials, ID resolution, and delivery of evidence bundles
belong to the host. A Trace Harness starts from raw span documents or normalized spans.

## 2. Pipeline

One configured harness executes these stages in order:

```text
raw spans -> normalize -> assemble -> eager features -> diagnose -> render
                                      \-> lazy features on explicit demand
                                      \-> probes on explicit host demand
```

1. `normalize` maps backend-specific span documents to `NormSpan` without assigning a semantic
   kind.
2. `assemble` applies ordered `KindSpec` values, fuses physical spans into logical `Node` values,
   creates parent edges, and bakes eager features and projections.
3. `diagnose` emits `Finding` values. Physical errors and per-kind rules run before scoped
   detectors. Detectors run in post-order and receive findings accumulated so far.
4. `render` applies scoped, declarative facets to `Node + Finding` and produces a display tree.
   Facets declare presentation intent such as the row projection and child layout; the harness
   owns traversal, display-tree construction, and output serialization. A renderer MAY expose
   lazy features in node details.
5. A probe MAY write evidence, but MUST run only after the host explicitly enables it. Importing
   a package, constructing a harness, assembling, diagnosing without probes, and rendering MUST
   NOT create evidence files.

Only `assemble` may create or change logical node parent edges. Later stages MUST be
structure-preserving.

## 3. Analysis IR

The canonical JSON projection is `trace-harness/analysis@1`, defined by
[`analysis.schema.json`](../schema/trace/v1/analysis.schema.json).

- `NormSpan` is one normalized physical span and retains raw data for provenance.
- `Node` is the analysis unit: one logical operation backed by one or more physical spans.
- `facts` contains named, JSON-compatible values derived from raw domain fields.
- `Finding` is an observation attached to a node, trace, or cohort. A finding is not a verdict.
- `brief` is the baked, language-neutral field projection used by renderers.

Implementations MUST order nodes by `(start_ms, node_id)` and findings by
`(scope, ref, source, severity, note)` when producing the canonical JSON projection. Runtime
collections do not otherwise need to use this order.

## 4. Scoped composition

`TraceHarness` is the state owner for one executable analysis configuration. It is reusable across
traces and MUST isolate its configuration from every other harness instance.

`TraceContributions` is the extension boundary used by a domain package or Plugin. It contains
four pure extension slots:

| Slot | Consumed by | Ordering rule |
| --- | --- | --- |
| `specs` | assemble and per-kind diagnose | first matching spec wins |
| `features` | eager bake and lazy detail | first applicable producer of a name wins |
| `detectors` | diagnose | declaration order within each post-order node |
| `facets` | render | highest priority wins; declaration order breaks ties |

Built-in contributions are copied into each harness before consumer contributions. A contribution
MUST NOT be installed by relying on module import side effects. Implementations MUST NOT expose an
ambient mutable registry as a contribution mechanism.

A facet MUST NOT replace the renderer or recurse through the analysis tree itself. This keeps
cross-domain presentation policy in the harness while still allowing each domain to state which
nodes are primary, summarized, grouped, or hidden. Findings remain renderer inputs, so generic and
domain detectors can affect emphasis without implementing presentation code.

Merging contributions preserves declaration order. It does not execute them.

## 5. Host and Plugin boundary

A host MAY receive `TraceContributions` from a Plugin and combine them with generic contributions.
The host remains responsible for data access and side effects.

- A deterministic offline host such as `doctor trace` SHOULD use specs, features, detectors, and
  facets, then emit Analysis IR or a report from the same scoped harness.
- An interactive investigation host MAY additionally expose lazy features such as `curl` or
  `messages`.
- Evidence probes are host capabilities, not ambient Plugin contributions, and MUST be enabled at
  the call site.

## 6. Conformance

Shared fixtures live under [`conformance/trace`](../conformance/trace). Every implementation
SHOULD:

1. normalize the shared raw-span fixture;
2. run it through a scoped harness with the declared generic specs;
3. compare its canonical Analysis IR exactly with the shared expected JSON;
4. verify that features, detectors, facets, and lazy features contributed to one harness do not
   affect another harness in the same process.

Numeric JSON equality follows JSON number semantics; `8000` and `8000.0` are equivalent.
