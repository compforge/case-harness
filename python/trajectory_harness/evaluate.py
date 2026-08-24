"""Evaluator contract and single-trajectory orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator_id": self.evaluator_id,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "owner": self.owner,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluatorSpec:
        return cls(
            evaluator_id=str(value["evaluator_id"]),
            title=str(value["title"]),
            description=str(value.get("description") or ""),
            kind=value.get("kind", "domain"),
            owner=str(value.get("owner") or ""),
        )


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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Finding:
        return cls(
            code=str(value["code"]),
            severity=value["severity"],
            summary=str(value.get("summary") or ""),
            step_ids=tuple(str(item) for item in value.get("step_ids", ())),
            hypotheses=tuple(str(item) for item in value.get("hypotheses", ())),
        )


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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluationResult:
        return cls(
            evaluator_id=str(value["evaluator_id"]),
            status=value["status"],
            verdict=value.get("verdict"),
            score=(float(value["score"]) if value.get("score") is not None else None),
            explanation=str(value.get("explanation") or ""),
            step_ids=tuple(str(item) for item in value.get("step_ids", ())),
            findings=tuple(
                Finding.from_dict(item) for item in value.get("findings", ())
            ),
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

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory.trajectory_id,
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, trajectory: Trajectory
    ) -> TrajectoryEvaluation:
        return cls(
            trajectory=trajectory,
            results=tuple(
                EvaluationResult.from_dict(item) for item in value.get("results", ())
            ),
        )


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
