"""Evaluate tool execution success across a trajectory."""

from __future__ import annotations

from dataclasses import dataclass

from trajectory_harness.evaluate import (
    EvaluationResult,
    EvaluatorSpec,
    MeasurementSpec,
)
from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class ToolSuccessEvaluator:
    spec: EvaluatorSpec = EvaluatorSpec(
        evaluator_id="tool_success",
        title="Tool success",
        description="Measure successful tool executions in the trajectory.",
        kind="common",
        owner="trajectory_harness",
        measurements=(
            MeasurementSpec("tool_call_count", "count", "Executed tool calls."),
            MeasurementSpec(
                "failed_call_count",
                "count",
                "Tool calls ending in failure.",
                "lower_is_better",
            ),
            MeasurementSpec(
                "success_rate",
                "ratio",
                "Successful tool calls divided by executed tool calls.",
                "higher_is_better",
            ),
        ),
    )

    def evaluate(
        self, trajectory: Trajectory, reference: Trajectory | None = None
    ) -> EvaluationResult:
        del reference
        calls = [step for step in trajectory.steps if step.operation == "execute_tool"]
        if not calls:
            return EvaluationResult(
                evaluator_id=self.spec.evaluator_id,
                status="not_applicable",
                explanation="Trajectory contains no executed tool calls.",
            )

        failed = [step for step in calls if step.failure or step.status == "error"]
        success_rate = round((len(calls) - len(failed)) / len(calls), 3)
        return EvaluationResult(
            evaluator_id=self.spec.evaluator_id,
            status="evaluated",
            verdict="pass" if not failed else "fail",
            score=success_rate,
            measurements={
                "tool_call_count": len(calls),
                "failed_call_count": len(failed),
                "success_rate": success_rate,
            },
            explanation=(
                f"{len(calls) - len(failed)} of {len(calls)} tool calls succeeded."
            ),
            step_ids=tuple(step.step_id for step in failed),
        )
