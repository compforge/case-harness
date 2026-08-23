"""Evaluate whether a trajectory reached a successful execution outcome."""

from __future__ import annotations

from dataclasses import dataclass

from trajectory_harness.evaluate import EvaluationResult, EvaluatorSpec
from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class ExecutionSuccessEvaluator:
    spec: EvaluatorSpec = EvaluatorSpec(
        evaluator_id="execution_success",
        title="Execution success",
        description="Check the authoritative final outcome of the trajectory.",
        kind="common",
        owner="trajectory_harness",
    )

    def evaluate(
        self, trajectory: Trajectory, reference: Trajectory | None = None
    ) -> EvaluationResult:
        del reference
        execution = trajectory.execution
        if execution is None or execution.outcome == "unknown":
            return EvaluationResult(
                evaluator_id=self.spec.evaluator_id,
                status="not_applicable",
                explanation="Trajectory has no authoritative execution outcome.",
            )

        success = execution.outcome == "completed"
        return EvaluationResult(
            evaluator_id=self.spec.evaluator_id,
            status="evaluated",
            verdict="pass" if success else "fail",
            score=1.0 if success else 0.0,
            explanation=f"Execution outcome is {execution.outcome}.",
        )
