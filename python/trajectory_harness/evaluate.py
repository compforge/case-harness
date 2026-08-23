"""Evaluator contract and single-trajectory orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from trajectory_harness.model import Trajectory

EvaluatorKind = Literal["common", "domain"]
EvaluationStatus = Literal["evaluated", "not_applicable", "error"]
Verdict = Literal["pass", "fail", "warning"]
FindingSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class EvaluatorSpec:
    """Stable catalog entry for one common or domain evaluator."""

    evaluator_id: str
    title: str
    description: str
    kind: EvaluatorKind = "domain"
    owner: str = ""


@dataclass(frozen=True, slots=True)
class Finding:
    """One evaluator finding, its evidence, and possible explanations."""

    code: str
    severity: FindingSeverity
    summary: str
    step_ids: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "summary": self.summary,
            "step_ids": list(self.step_ids),
            "hypotheses": list(self.hypotheses),
        }


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """One evaluator's quality conclusion and diagnostic findings."""

    evaluator_id: str
    status: EvaluationStatus
    verdict: Verdict | None = None
    score: float | None = None
    explanation: str = ""
    step_ids: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()

    def to_dict(self) -> dict:
        return {
            "evaluator_id": self.evaluator_id,
            "status": self.status,
            "verdict": self.verdict,
            "score": self.score,
            "explanation": self.explanation,
            "step_ids": list(self.step_ids),
            "findings": [finding.to_dict() for finding in self.findings],
        }


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

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory.trajectory_id,
            "results": [result.to_dict() for result in self.results],
        }


def evaluate(
    trajectory: Trajectory,
    evaluators: list[Evaluator] | tuple[Evaluator, ...],
    *,
    reference: Trajectory | None = None,
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
    return TrajectoryEvaluation(trajectory=trajectory, results=tuple(results))
