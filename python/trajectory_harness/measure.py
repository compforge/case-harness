"""Measurement contract and single-trajectory orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from trajectory_harness.model import Trajectory

MeasurementStatus = Literal["measured", "not_applicable", "error"]
MetricDirection = Literal["higher_is_better", "lower_is_better", "neutral"]
Aggregation = Literal["sum", "mean", "p50", "p95"]
Measurement = float | int | bool


@dataclass(frozen=True, slots=True)
class MeasurementSpec:
    """One factual value produced for a trajectory."""

    name: str
    unit: str = ""
    description: str = ""
    direction: MetricDirection = "neutral"
    aggregations: tuple[Aggregation, ...] = ("mean",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "description": self.description,
            "direction": self.direction,
            "aggregations": list(self.aggregations),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MeasurementSpec:
        return cls(
            name=str(value["name"]),
            unit=str(value.get("unit") or ""),
            description=str(value.get("description") or ""),
            direction=value.get("direction", "neutral"),
            aggregations=tuple(value.get("aggregations", ("mean",))),
        )


@dataclass(frozen=True, slots=True)
class MeasurerSpec:
    """Stable catalog entry for one trajectory measurer."""

    measurer_id: str
    title: str
    description: str
    owner: str = ""
    measurements: tuple[MeasurementSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurer_id": self.measurer_id,
            "title": self.title,
            "description": self.description,
            "owner": self.owner,
            "measurements": [item.to_dict() for item in self.measurements],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MeasurerSpec:
        return cls(
            measurer_id=str(value["measurer_id"]),
            title=str(value["title"]),
            description=str(value.get("description") or ""),
            owner=str(value.get("owner") or ""),
            measurements=tuple(
                MeasurementSpec.from_dict(item)
                for item in value.get("measurements", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class MeasurementResult:
    """One measurer's factual observations, without a quality conclusion."""

    measurer_id: str
    status: MeasurementStatus
    measurements: dict[str, Measurement] = field(default_factory=dict)
    explanation: str = ""
    step_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "measurer_id": self.measurer_id,
            "status": self.status,
            "measurements": dict(self.measurements),
            "explanation": self.explanation,
            "step_ids": list(self.step_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MeasurementResult:
        return cls(
            measurer_id=str(value["measurer_id"]),
            status=value["status"],
            measurements=dict(value.get("measurements") or {}),
            explanation=str(value.get("explanation") or ""),
            step_ids=tuple(str(item) for item in value.get("step_ids", ())),
        )


@runtime_checkable
class Measurer(Protocol):
    """Observe one trajectory without judging its quality."""

    spec: MeasurerSpec

    def measure(self, trajectory: Trajectory) -> MeasurementResult: ...


@dataclass(frozen=True, slots=True)
class TrajectoryMeasurement:
    """A trajectory paired with all measurement results produced for it."""

    trajectory: Trajectory
    results: tuple[MeasurementResult, ...]

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory.trajectory_id,
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, trajectory: Trajectory
    ) -> TrajectoryMeasurement:
        return cls(
            trajectory=trajectory,
            results=tuple(
                MeasurementResult.from_dict(item) for item in value.get("results", ())
            ),
        )


def measure(
    trajectory: Trajectory,
    measurers: list[Measurer] | tuple[Measurer, ...],
) -> TrajectoryMeasurement:
    """Run measurers; plugin failures remain health data, never measurements."""

    results = []
    for measurer in measurers:
        try:
            results.append(measurer.measure(trajectory))
        except Exception as error:  # measurer plugins are an isolation boundary
            results.append(
                MeasurementResult(
                    measurer_id=measurer.spec.measurer_id,
                    status="error",
                    explanation=f"{type(error).__name__}: {error}",
                )
            )
    return TrajectoryMeasurement(trajectory=trajectory, results=tuple(results))
