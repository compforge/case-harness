"""Evaluator contract and single-trajectory orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from trajectory_harness.model import Trajectory

EvaluatorKind = Literal["common", "domain"]
EvaluationStatus = Literal["evaluated", "not_applicable", "error"]
Verdict = Literal["pass", "fail", "warning"]


@dataclass(frozen=True, slots=True)
class EvaluatorSpec:
    """Stable catalog entry for one common or domain evaluator."""

    evaluator_id: str
    title: str
    description: str
    kind: EvaluatorKind = "domain"
    owner: str = ""
    category: str = "quality"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator_id": self.evaluator_id,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "owner": self.owner,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluatorSpec:
        return cls(
            evaluator_id=str(value["evaluator_id"]),
            title=str(value["title"]),
            description=str(value.get("description") or ""),
            kind=value.get("kind", "domain"),
            owner=str(value.get("owner") or ""),
            category=str(value.get("category") or "quality"),
        )


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """One evaluator's quality conclusion and supporting evidence."""

    evaluator_id: str
    status: EvaluationStatus
    verdict: Verdict | None = None
    score: float | None = None
    explanation: str = ""
    step_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status == "evaluated" and self.verdict is None and self.score is None:
            raise ValueError(
                "an evaluated result must provide a verdict, a score, or both"
            )

    def to_dict(self) -> dict:
        return {
            "evaluator_id": self.evaluator_id,
            "status": self.status,
            "verdict": self.verdict,
            "score": self.score,
            "explanation": self.explanation,
            "step_ids": list(self.step_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluationResult:
        return cls(
            evaluator_id=str(value["evaluator_id"]),
            status=value["status"],
            verdict=value.get("verdict"),
            score=(float(value["score"]) if value.get("score") is not None else None),
            explanation=str(value.get("explanation") or ""),
            step_ids=tuple(str(item) for item in value.get("step_ids", ())),
        )


@runtime_checkable
class Evaluator(Protocol):
    """Judge one trajectory without knowing its source recording format."""

    spec: EvaluatorSpec

    def evaluate(
        self, trajectory: Trajectory, reference: Trajectory | None = None
    ) -> EvaluationResult: ...


@dataclass(frozen=True, slots=True)
class TrajectoryEvaluation:
    """A trajectory paired with all evaluator results produced for it."""

    trajectory: Trajectory
    results: tuple[EvaluationResult, ...]
    target: str = ""
    category: str = "quality"

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory.trajectory_id,
            "target": self.target,
            "category": self.category,
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, trajectory: Trajectory
    ) -> TrajectoryEvaluation:
        return cls(
            trajectory=trajectory,
            target=str(value.get("target") or ""),
            category=str(value.get("category") or "quality"),
            results=tuple(
                EvaluationResult.from_dict(item) for item in value.get("results", ())
            ),
        )


def evaluate(
    trajectory: Trajectory,
    evaluators: list[Evaluator] | tuple[Evaluator, ...],
    *,
    reference: Trajectory | None = None,
    target: str = "",
    category: str = "quality",
) -> TrajectoryEvaluation:
    """Run evaluators; evaluator failures remain health data, never a zero score."""

    results = []
    for evaluator in evaluators:
        try:
            results.append(evaluator.evaluate(trajectory, reference))
        except Exception as error:  # evaluator plugins are an isolation boundary
            results.append(
                EvaluationResult(
                    evaluator_id=evaluator.spec.evaluator_id,
                    status="error",
                    explanation=f"{type(error).__name__}: {error}",
                )
            )
    return TrajectoryEvaluation(
        trajectory=trajectory,
        results=tuple(results),
        target=target,
        category=category,
    )
