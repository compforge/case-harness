"""common — harness-neutral shared code (report_kit / verdict / facets / case).

The 4 harnesses (e2e / eval / perf / trace) depend on this package but never on each
other; only genuinely neutral code lives here (no harness domain concept leaks in).

`Face` / `FACES` are the **judgment faces** — the cross-cutting enum that ties the input
contract to the output contract: a case declares criteria per face (`case.judge.<face>`)
and the harness for that face produces a verdict for it (`verdict.harness`). Both
`common.case` and `common.verdict` reference this single enum.

NB: a *face* (判定面: how a case is judged — 对错/效果/容量) is NOT a *facet* (分类轴: how a
case is classified — difficulty/lang/type, see `common.facets`). Different concepts that
happen to look alike; keep them apart.
"""

from __future__ import annotations

from typing import Literal

# the judgment faces (= the harnesses a canonical case / run can be judged by).
# trace judges open-box (declared gates over telemetry-derived tables → checks[]), the
# other three judge black-box responses; all four share the same verdict wire.
# 口味/taste is NOT here: it judges the diff/code, not a SUT request, so it has no case.
Face = Literal["e2e", "eval", "perf", "trace"]
FACES: tuple[Face, ...] = ("e2e", "eval", "perf", "trace")
