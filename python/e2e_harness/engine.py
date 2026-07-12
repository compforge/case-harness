"""0→1 e2e engine — run a structured ``common.Case`` and emit a ``CaseVerdict`` for the e2e face.

The whole e2e face as one data-driven sentence::

    build a Request from case.input → fire it via a Runner (the protocol adapter: JSON / SSE)
    → normalize the Outcome into a response view → run case.judge["e2e"]["assert"] over it
    → CaseVerdict.

No scaffold, no per-case test class: the case data carries both the stimulus (``input``) and
the judgment (``judge.e2e.assert``); this engine executes them generically over the reusable
``runner.Runner`` adapter. Per-case status:

- **skipped** — no ``e2e`` face on the case (its judgment belongs to eval/perf); e2e doesn't fire it.
- **error** — an ``e2e`` face is declared but has no ``assert`` (an unfilled casegen draft), OR the
  runner couldn't fire. Either way the run is untrustworthy → ``error`` wins the rollup, so an
  unfilled draft can NOT be hidden green by a sibling ``pass``.
- **pass / fail** — fired and every / not-every assertion held.
"""

from __future__ import annotations

from harness_common.case import Case
from harness_common.verdict import RunVerdict, build_run_verdict
from harness_common.verdict import CaseVerdict
from e2e_harness.assertion import Assertion, run_asserts
from e2e_harness.runner.base import BaseRunner, Outcome, Request


def response_view(outcome: Outcome) -> dict:
    """Normalize an ``Outcome`` into the flat dict that assertion paths address.

    Paths are uniform over this view: ``status`` (the code), ``body.<…>``, ``headers.<…>``,
    ``events[].<…>`` + ``event_count`` (SSE frames, from ``Outcome.metadata``), ``duration_ms``.
    """
    events = outcome.metadata.get("events", [])
    return {
        "status": outcome.status_code,
        "body": outcome.body,
        "headers": outcome.headers,
        "events": events,
        "event_count": outcome.metadata.get("event_count", len(events)),
        "duration_ms": outcome.duration_ms,
    }


def _request_of(case: Case) -> Request:
    """Project ``case.input`` (schemaless) into a runner ``Request``.

    Recognised keys: ``method`` / ``path`` / ``body`` / ``headers`` / ``query``. Unknown keys
    are ignored here — a protocol-specific runner may read them off ``case.input`` itself.
    """
    inp = case.input or {}
    return Request(
        method=str(inp.get("method", "POST")),
        path=str(inp.get("path", "")),
        body=inp.get("body"),
        headers={k: str(v) for k, v in (inp.get("headers") or {}).items()},
        query={k: str(v) for k, v in (inp.get("query") or {}).items()},
    )


def run_case(case: Case, runner: BaseRunner) -> CaseVerdict:
    """Fire one case through ``runner`` and judge its e2e face → one ``CaseVerdict``."""
    judge = case.judge or {}
    if "e2e" not in judge:
        # no e2e face: this case's judgment belongs to another face (eval/perf). e2e neither
        # fires nor judges it → skipped. (Cross-face "observe" is another face's job, not e2e's.)
        return CaseVerdict(
            case_id=case.id,
            status="skipped",
            reason="no e2e face",
            facets=dict(case.facets),
        )
    raw_asserts = (judge.get("e2e") or {}).get("assert") or []
    if not raw_asserts:
        # an e2e face is DECLARED but carries no assertions → an unfilled draft (casegen leaves
        # asserts empty for fill). It can't be judged, so it must NOT count as green: ``error``
        # (untrustworthy — wins the rollup) rather than ``skipped`` (which a sibling pass hides).
        return CaseVerdict(
            case_id=case.id,
            status="error",
            reason="judge.e2e declared but no assert — draft not filled",
            facets=dict(case.facets),
        )
    try:
        outcome = runner.trigger(_request_of(case))
    except Exception as e:  # noqa: BLE001 — any fire failure is an errored case, not a fail
        return CaseVerdict(
            case_id=case.id,
            status="error",
            reason=f"could not fire: {type(e).__name__}: {e}",
            facets=dict(case.facets),
        )
    results = run_asserts(
        [Assertion.from_dict(a) for a in raw_asserts], response_view(outcome)
    )
    failed = [r for r in results if not r.ok]
    if failed:
        return CaseVerdict(
            case_id=case.id,
            status="fail",
            reason="; ".join(r.detail for r in failed[:3]),
            facets=dict(case.facets),
        )
    return CaseVerdict(case_id=case.id, status="pass", facets=dict(case.facets))


def run_cases(
    cases: list[Case], runner: BaseRunner, *, scope: str, run_id: str
) -> RunVerdict:
    """Run every case → one e2e ``RunVerdict`` (status = rollup over the per-case verdicts)."""
    verdicts = [run_case(c, runner) for c in cases]
    return build_run_verdict("e2e", scope, run_id, verdicts)
