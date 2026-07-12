"""Project a perf Run into the cross-harness ``verdict.json`` (spec/verdict-schema.yaml).

The schema/serialization lives in `common.verdict`; this keeps only perf's projection.
perf judges at the *run* level via the SLO gate, and its judged unit is the **SLO check**
(an assertion on an aggregate / facet slice), NOT a case — so the verdict carries no
``cases`` rows; each SLO check becomes a `common.verdict.CheckVerdict` in ``checks``.
``summary`` (which always counts cases) is therefore omitted; perf's scale is ``len(checks)``.
"""

from __future__ import annotations

from pathlib import Path

from harness_common import verdict as _v

from perf_harness.model import Run, SloCheck


def _check_verdict(c: SloCheck) -> _v.CheckVerdict:
    """One SLO check → a CheckVerdict. ``skipped`` iff the metric's slice had no value
    (``observed is None``) — a skip is not a pass; otherwise the check's own state."""
    a = c.assertion
    name = f"{a.metric} {a.op} {a.threshold}"
    if a.level is not None:
        name += f" @level={a.level}"
    status = "skipped" if c.observed is None else c.state
    return _v.CheckVerdict(name=name, status=status, metric=a.metric, observed=c.observed)


def _build(run: Run) -> _v.RunVerdict:
    """Run → RunVerdict. status is the *recorded* SLO-gate verdict, derived from the
    per-trial check states with the cross-harness rollup precedence (fail > pass >
    skipped) — deliberately NOT from ``run.passed``. ``run.passed`` is the engine's
    *operational* gate (exit code / abort / ``strict_slo`` leniency) and by default lets
    a skipped check slide; the recorded verdict must not, or a capacity run whose SLO
    never evaluated (every slice absent, or no SLO declared) would read green and a
    verdict consumer would trust an unverified run. So: any real fail → fail; else any
    real pass → pass; else (all skipped / nothing declared) → skipped."""
    raw: list[SloCheck] = [c for t in run.trials for c in t.slo]
    n_pass = sum(1 for c in raw if c.state == "pass")
    n_fail = sum(1 for c in raw if c.state == "fail" and c.observed is not None)

    if not run.trials:
        status = "skipped"
    elif n_fail:
        status = "fail"
    elif n_pass:
        status = "pass"
    else:
        status = "skipped"  # SLO declared but every check skipped, or no SLO at all
    reason = (
        _fail_reason([c for c in raw if c.state == "fail" and c.observed is not None])
        if status == "fail"
        else None
    )

    return _v.build_run_verdict(
        "perf",
        run.experiment,
        run.run_id,
        [],
        checks=[_check_verdict(c) for c in raw],
        status=status,
        reason=reason,
        artifact_paths={"run": "run.json", "report": "report.md"},
        created_at=run.created_at,
    )


def _fail_reason(failed: list[SloCheck]) -> str:
    first = failed[0]
    a = first.assertion
    detail = f"{a.metric} {a.op} {a.threshold} (observed {first.observed})"
    return f"{len(failed)} SLO failed; first — {detail}"


def build_verdict_doc(run: Run) -> dict:
    return _build(run).to_dict()


def write_verdict(run_dir: str | Path, run: Run) -> Path:
    """Write ``verdict.json`` into ``run_dir``. Returns its path."""
    return _v.write_verdict(run_dir, _build(run))
