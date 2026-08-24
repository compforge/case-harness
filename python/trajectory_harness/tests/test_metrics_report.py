from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from trajectory_harness import (
    EvaluationSlice,
    ExecutionResult,
    ExecutionSuccessEvaluator,
    Failure,
    Metric,
    Step,
    Trajectory,
    TrajectoryEvaluationRun,
    aggregate_metrics,
    evaluate,
    render_report_html,
)


def _run(run_id: str, day: int, success: bool) -> TrajectoryEvaluationRun:
    failure = None
    if not success:
        failure = Failure(
            kind="llm",
            phase="request",
            error_type="timeout",
            code="APITimeoutError",
        )
    trajectory = Trajectory(
        trajectory_id=f"trajectory-{run_id}",
        steps=(
            Step(
                step_id=f"step-{run_id}",
                parent_step_id=None,
                operation="chat",
                name="model",
                start_ms=0,
                duration_ms=10,
                status="error" if failure else "ok",
                failure=failure,
            ),
        ),
        execution=ExecutionResult(
            outcome="completed" if success else "timeout",
            duration_ms=10 if success else 30,
            failure=failure,
        ),
    )
    evaluator = ExecutionSuccessEvaluator()
    return TrajectoryEvaluationRun(
        run_id=run_id,
        created_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        dataset_id="reviews",
        dataset_version="",
        slices=(
            EvaluationSlice(
                slice_id="unit",
                trajectory_ids=(trajectory.trajectory_id,),
                evaluations=(evaluate(trajectory, [evaluator]),),
                evaluator_specs=(evaluator.spec,),
                annotation_count=1,
            ),
        ),
    )


def test_aggregate_metrics_combines_execution_failure_and_evaluation():
    metrics = aggregate_metrics(_run("run-2", 2, False))
    by_name = {metric.qualified_name: metric.value for metric in metrics}

    assert by_name["execution.timeout.rate"] == 1
    assert by_name["evaluation.pass.rate{evaluator_id=execution_success}"] == 0
    assert (
        by_name[
            "failure.count{impact=execution,kind=llm,phase=request,error_type=timeout}"
        ]
        == 1
    )
    assert Metric.from_dict(metrics[0].to_dict()) == metrics[0]
    assert TrajectoryEvaluationRun.from_dict(
        _run("roundtrip", 2, False).to_dict()
    ) == _run("roundtrip", 2, False)


def test_html_report_contains_catalog_failures_and_categorical_trends():
    runs = [_run("baseline", 1, True), _run("candidate", 3, False)]
    persisted_metrics = [metric for run in runs for metric in aggregate_metrics(run)]
    html = render_report_html(
        runs,
        title="Weekly trajectory quality",
        metrics=persisted_metrics,
    )

    assert "Weekly trajectory quality" in html
    assert "execution_success" in html
    assert "timeout" in html
    assert "trajectory-candidate" in html
    assert "APITimeoutError" in html
    assert '"type": "time"' in html
    assert "2026-08-01T00:00:00+00:00" in html
    assert "2026-08-03T00:00:00+00:00" in html


def test_html_counts_top_level_runs_instead_of_slices():
    run = _run("multi-slice", 2, True)
    run = replace(
        run,
        slices=(
            run.slices[0],
            replace(run.slices[0], slice_id="another-unit"),
        ),
    )

    html = render_report_html([run])

    assert "Runs:</b> 1" in html
    assert "reviews/unit" in html
    assert "reviews/another-unit" in html
    assert '"type": "time"' not in html
