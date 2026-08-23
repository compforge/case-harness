"""Evaluate tool execution success across a trajectory."""

from __future__ import annotations

from dataclasses import dataclass

from trajectory_harness.evaluate import EvaluationResult, EvaluatorSpec
from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class ToolSuccessEvaluator:
    spec: EvaluatorSpec = EvaluatorSpec(
        evaluator_id="tool_success",
        title="Tool success",
        description="Judge whether tool executions in the trajectory succeeded.",
        kind="common",
        owner="trajectory_harness",
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
            explanation=(
                f"{len(calls) - len(failed)} of {len(calls)} tool calls succeeded."
            ),
            step_ids=tuple(step.step_id for step in failed),
        )
