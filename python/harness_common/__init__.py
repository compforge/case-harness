"""common — harness-neutral shared code (report_kit / verdict / llm / run / overlay).

The harnesses (e2e / eval / perf / trace / trajectory) depend on this package but never on each
other; only genuinely neutral code lives here (no harness domain concept leaks in).

The canonical case model — `Case` / `CaseSet` / `FacetSchema` and the `Face` / `FACES`
judgment-face enum — lives upstream in `spec_case.model` / `spec_case.facets`
(the spec-case package, `[model]` extra): the case format is the asset layer's contract,
and this repo is one of its runners. Import those names from `spec_case` directly.
"""

from __future__ import annotations
