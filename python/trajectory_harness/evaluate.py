"""Evaluator contract and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One normalized 0..1 assessment, aligned with OTel evaluation fields."""

    name: str
    score: float | None
    label: str = ""
    explanation: str = ""
    step_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "label": self.label,
            "explanation": self.explanation,
            "step_ids": list(self.step_ids),
        }


@runtime_checkable
class Evaluator(Protocol):
    """Judge one trajectory; ``None`` score means not applicable, never zero."""

    name: str
    weight: float

    def evaluate(
        self, trajectory: Trajectory, reference: Trajectory | None = None
    ) -> Evaluation: ...


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    trajectory_id: str
    score: float | None
    evaluations: tuple[Evaluation, ...]

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory_id,
            "score": self.score,
            "evaluations": [evaluation.to_dict() for evaluation in self.evaluations],
        }


def evaluate(
    trajectory: Trajectory,
    evaluators: list[Evaluator] | tuple[Evaluator, ...],
    *,
    reference: Trajectory | None = None,
) -> EvaluationReport:
    """Run evaluators and average applicable scores by their positive weights."""

    results = tuple(
        evaluator.evaluate(trajectory, reference) for evaluator in evaluators
    )
    weighted = [
        (result.score, evaluator.weight)
        for evaluator, result in zip(evaluators, results)
        if result.score is not None and evaluator.weight > 0
    ]
    total_weight = sum(weight for _, weight in weighted)
    score = (
        round(sum(score * weight for score, weight in weighted) / total_weight, 3)
        if total_weight
        else None
    )
    return EvaluationReport(
        trajectory_id=trajectory.trajectory_id,
        score=score,
        evaluations=results,
    )
