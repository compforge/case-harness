from __future__ import annotations

from dataclasses import dataclass

import pytest

from trajectory_harness import (
    DetectionResult,
    DetectorSpec,
    EvaluationResult,
    EvaluatorSpec,
    ExecutionResult,
    ExecutionSuccessEvaluator,
    Failure,
    Finding,
    RepeatedToolCallDetector,
    Step,
    ToolSuccessEvaluator,
    Trajectory,
    detect,
    evaluate,
)


def _tool_step(step_id: str, path: str, *, failure: Failure | None = None) -> Step:
    return Step(
        step_id=step_id,
        parent_step_id=None,
        operation="execute_tool",
        name="file_read",
        start_ms=0,
        duration_ms=1,
        status="error" if failure else "ok",
        failure=failure,
        input_messages=(
            {
                "role": "assistant",
                "parts": [
                    {
                        "type": "tool_call",
                        "name": "file_read",
                        "arguments": {"path": path},
                    }
                ],
            },
        ),
    )


def test_repeated_tool_call_detector_returns_finding_and_evidence():
    trajectory = Trajectory(
        trajectory_id="t1",
        steps=(
            _tool_step("s1", "a.go"),
            _tool_step("s2", "b.go"),
            _tool_step("s3", "a.go"),
        ),
    )

    detection = detect(trajectory, [RepeatedToolCallDetector()])

    result = detection.results[0]
    assert result.status == "analyzed"
    assert result.findings == (
        Finding(
            code="repeated_tool_call",
            severity="warning",
            summary="1 of 3 tool calls repeat an earlier tool name and arguments.",
            step_ids=("s3",),
            hypotheses=(
                "The tool may be missing a batch operation.",
                "The tool description may not encourage batching or result reuse.",
                "The agent loop may lack an effective repeat-call stopping strategy.",
            ),
        ),
    )
    assert result.to_dict()["findings"][0]["step_ids"] == ["s3"]


def test_detector_is_not_applicable_when_trajectory_has_no_tool_calls():
    trajectory = Trajectory(
        trajectory_id="t1",
        steps=(
            Step(
                step_id="s1",
                parent_step_id=None,
                operation="chat",
                name="model",
                start_ms=0,
                duration_ms=1,
            ),
        ),
    )

    detection = detect(trajectory, [RepeatedToolCallDetector()])

    assert detection.results[0].status == "not_applicable"
    assert detection.results[0].findings == ()


def test_model_round_tool_calls_are_fallback_when_tool_spans_are_absent():
    trajectory = Trajectory(
        trajectory_id="t1",
        steps=tuple(
            Step(
                step_id=f"s{index}",
                parent_step_id=None,
                operation="chat",
                name="model",
                start_ms=index,
                duration_ms=1,
                output_messages=(
                    {
                        "role": "assistant",
                        "parts": [
                            {
                                "type": "tool_call",
                                "name": "code_search",
                                "arguments": {"query": "foo"},
                            }
                        ],
                    },
                ),
            )
            for index in (1, 2)
        ),
    )

    result = RepeatedToolCallDetector().detect(trajectory)

    assert result.findings[0].step_ids == ("s2",)


def test_common_execution_and_tool_evaluators_keep_failures_as_facts():
    failure = Failure(
        kind="tool",
        phase="prepare",
        error_type="dependency_missing",
        code="ENOENT",
    )
    trajectory = Trajectory(
        trajectory_id="t1",
        steps=(_tool_step("s1", "a.go", failure=failure),),
        execution=ExecutionResult(outcome="failed", duration_ms=25, failure=failure),
    )

    evaluation = evaluate(
        trajectory, [ExecutionSuccessEvaluator(), ToolSuccessEvaluator()]
    )

    execution, tool = evaluation.results
    assert execution.verdict == "fail"
    assert execution.score == 0
    assert tool.verdict == "fail"
    assert tool.score == 0
    assert tool.step_ids == ("s1",)


def test_failure_and_execution_round_trip_with_trajectory():
    failure = Failure(
        kind="llm",
        phase="request",
        error_type="rate_limit",
        code="429",
        message="too many requests",
    )
    original = Trajectory(
        trajectory_id="t1",
        steps=(
            Step(
                step_id="s1",
                parent_step_id=None,
                operation="chat",
                name="model",
                start_ms=1,
                duration_ms=2,
                status="error",
                failure=failure,
            ),
        ),
        execution=ExecutionResult(outcome="failed", duration_ms=2, failure=failure),
    )

    restored = Trajectory.from_dict(original.to_dict())

    assert restored == original
    assert restored.steps[0].failure.key == "llm.request.rate_limit"


def test_evaluator_exception_is_health_data_not_zero_score():
    @dataclass(frozen=True)
    class BrokenEvaluator:
        spec: EvaluatorSpec = EvaluatorSpec(
            evaluator_id="broken",
            title="Broken",
            description="Test evaluator failure.",
        )

        def evaluate(self, trajectory, reference=None):
            del trajectory, reference
            raise RuntimeError("judge unavailable")

    evaluation = evaluate(Trajectory(trajectory_id="t1", steps=()), [BrokenEvaluator()])

    assert evaluation.results == (
        EvaluationResult(
            evaluator_id="broken",
            status="error",
            explanation="RuntimeError: judge unavailable",
        ),
    )


def test_detector_exception_is_health_data():
    @dataclass(frozen=True)
    class BrokenDetector:
        spec: DetectorSpec = DetectorSpec(
            detector_id="broken",
            title="Broken",
            description="Test detector failure.",
        )

        def detect(self, trajectory):
            del trajectory
            raise RuntimeError("detector unavailable")

    detection = detect(Trajectory(trajectory_id="t1", steps=()), [BrokenDetector()])

    assert detection.results == (
        DetectionResult(
            detector_id="broken",
            status="error",
            explanation="RuntimeError: detector unavailable",
        ),
    )


def test_evaluated_result_requires_a_judgment():
    with pytest.raises(ValueError, match="verdict, a score, or both"):
        EvaluationResult(evaluator_id="empty", status="evaluated")
