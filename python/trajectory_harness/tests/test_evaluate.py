from __future__ import annotations

from trajectory_harness import RepeatedToolCallEvaluator, Step, Trajectory, evaluate


def _tool_step(step_id: str, path: str) -> Step:
    return Step(
        step_id=step_id,
        parent_step_id=None,
        operation="execute_tool",
        name="file_read",
        start_ms=0,
        duration_ms=1,
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


def test_repeated_tool_call_evaluator_scores_exact_repeats():
    trajectory = Trajectory(
        trajectory_id="t1",
        steps=(
            _tool_step("s1", "a.go"),
            _tool_step("s2", "b.go"),
            _tool_step("s3", "a.go"),
        ),
    )

    report = evaluate(trajectory, [RepeatedToolCallEvaluator()])

    assert report.score == 0.667
    assert report.evaluations[0].label == "fail"
    assert report.evaluations[0].step_ids == ("s3",)


def test_evaluator_abstains_when_trajectory_has_no_tool_calls():
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

    report = evaluate(trajectory, [RepeatedToolCallEvaluator()])

    assert report.score is None
    assert report.evaluations[0].label == "not_evaluated"


def test_model_round_tool_calls_are_fallback_when_tool_spans_are_absent():
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
            ),
            Step(
                step_id="s2",
                parent_step_id=None,
                operation="chat",
                name="model",
                start_ms=2,
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
            ),
        ),
    )

    result = RepeatedToolCallEvaluator().evaluate(trajectory)

    assert result.score == 0.5
    assert result.step_ids == ("s2",)
