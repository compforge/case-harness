"""Detector contract and single-trajectory finding discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from trajectory_harness.model import Trajectory

DetectorKind = Literal["common", "domain"]
DetectionStatus = Literal["analyzed", "not_applicable", "error"]
FindingSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class DetectorSpec:
    """Stable catalog entry for one common or domain detector."""

    detector_id: str
    title: str
    description: str
    kind: DetectorKind = "domain"
    owner: str = ""
    category: str = "behavior"

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_id": self.detector_id,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "owner": self.owner,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DetectorSpec:
        return cls(
            detector_id=str(value["detector_id"]),
            title=str(value["title"]),
            description=str(value.get("description") or ""),
            kind=value.get("kind", "domain"),
            owner=str(value.get("owner") or ""),
            category=str(value.get("category") or "behavior"),
        )


@dataclass(frozen=True, slots=True)
class Finding:
    """One detector finding, its evidence, and possible explanations."""

    code: str
    severity: FindingSeverity
    summary: str
    step_ids: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
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
class DetectionResult:
    """One detector's findings without making a quality verdict."""

    detector_id: str
    status: DetectionStatus
    findings: tuple[Finding, ...] = ()
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_id": self.detector_id,
            "status": self.status,
            "findings": [finding.to_dict() for finding in self.findings],
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DetectionResult:
        return cls(
            detector_id=str(value["detector_id"]),
            status=value["status"],
            findings=tuple(
                Finding.from_dict(item) for item in value.get("findings", ())
            ),
            explanation=str(value.get("explanation") or ""),
        )


@runtime_checkable
class Detector(Protocol):
    """Discover findings in one normalized trajectory."""

    spec: DetectorSpec

    def detect(self, trajectory: Trajectory) -> DetectionResult: ...


@dataclass(frozen=True, slots=True)
class TrajectoryDetection:
    """A trajectory paired with all detector results produced for it."""

    trajectory: Trajectory
    results: tuple[DetectionResult, ...]
    target: str = ""
    category: str = "behavior"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory.trajectory_id,
            "target": self.target,
            "category": self.category,
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, trajectory: Trajectory
    ) -> TrajectoryDetection:
        return cls(
            trajectory=trajectory,
            target=str(value.get("target") or ""),
            category=str(value.get("category") or "behavior"),
            results=tuple(
                DetectionResult.from_dict(item) for item in value.get("results", ())
            ),
        )


def detect(
    trajectory: Trajectory,
    detectors: list[Detector] | tuple[Detector, ...],
    *,
    target: str = "",
    category: str = "behavior",
) -> TrajectoryDetection:
    """Run detectors; detector failures remain health data."""

    results = []
    for detector in detectors:
        try:
            results.append(detector.detect(trajectory))
        except Exception as error:  # detector plugins are an isolation boundary
            results.append(
                DetectionResult(
                    detector_id=detector.spec.detector_id,
                    status="error",
                    explanation=f"{type(error).__name__}: {error}",
                )
            )
    return TrajectoryDetection(
        trajectory=trajectory,
        results=tuple(results),
        target=target,
        category=category,
    )
