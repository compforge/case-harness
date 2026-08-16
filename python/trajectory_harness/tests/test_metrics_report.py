from __future__ import annotations

from datetime import datetime, timezone

from trajectory_harness import (
    DatasetRef,
    EvaluationRun,
    ExecutionResult,
    ExecutionSuccessEvaluator,
    Failure,
    Metric,
    Step,
    Trajectory,
    aggregate_metrics,
    evaluate,
    render_report_html,
)


def _run(run_id: str, day: int, success: bool) -> EvaluationRun:
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
    return EvaluationRun(
        run_id=run_id,
        created_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        dataset=DatasetRef("reviews", slice="unit", sample_count=1),
        items=(evaluate(trajectory, [evaluator]),),
        evaluator_specs=(evaluator.spec,),
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
