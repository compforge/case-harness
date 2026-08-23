"""Measurement contract and single-trajectory orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

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


@dataclass(frozen=True, slots=True)
class MeasurerSpec:
    """Stable catalog entry for one trajectory measurer."""

    measurer_id: str
    title: str
    description: str
    owner: str = ""
    measurements: tuple[MeasurementSpec, ...] = ()


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
