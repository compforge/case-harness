"""Trajectory evaluation runs, slices, and generic metric aggregation."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal

from trajectory_harness.evaluate import EvaluatorSpec, TrajectoryEvaluation
from trajectory_harness.measure import (
    MetricDirection,
    MeasurerSpec,
    TrajectoryMeasurement,
)
from trajectory_harness.model import Trajectory

MetricAggregation = Literal["count", "rate", "sum", "mean", "p50", "p95"]


@dataclass(frozen=True, slots=True)
class EvaluationSlice:
    """One comparison slice inside a trajectory evaluation run."""

    slice_id: str
    trajectory_ids: tuple[str, ...]
    evaluations: tuple[TrajectoryEvaluation, ...]
    evaluator_specs: tuple[EvaluatorSpec, ...] = ()
    measurements: tuple[TrajectoryMeasurement, ...] = ()
    measurer_specs: tuple[MeasurerSpec, ...] = ()
    annotation_count: int | None = None
    metrics: tuple[Metric, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.slice_id or "all"


@dataclass(frozen=True, slots=True)
class TrajectoryEvaluationRun:
    """One configured evaluation of a fixed trajectory dataset version."""

    run_id: str
    created_at: datetime
    dataset_id: str
    dataset_version: str
    slices: tuple[EvaluationSlice, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def metrics(self) -> tuple[Metric, ...]:
        return tuple(metric for slice_ in self.slices for metric in slice_.metrics)

    def slice_label(self, slice_: EvaluationSlice) -> str:
        return (
            f"{self.dataset_id}/{slice_.slice_id}"
            if slice_.slice_id
            else self.dataset_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "trajectories": [item.to_dict() for item in _run_trajectories(self)],
            "slices": [_slice_to_dict(item) for item in self.slices],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrajectoryEvaluationRun:
        trajectories = {
            trajectory.trajectory_id: trajectory
            for trajectory in (
                Trajectory.from_dict(item) for item in value.get("trajectories", ())
            )
        }

        def trajectory_for(item: dict[str, Any]) -> Trajectory:
            trajectory_id = str(item["trajectory_id"])
            try:
                return trajectories[trajectory_id]
            except KeyError as error:
                raise ValueError(
                    f"run item references unknown trajectory {trajectory_id!r}"
                ) from error

        def slice_from_dict(item: dict[str, Any]) -> EvaluationSlice:
            return EvaluationSlice(
                slice_id=str(item.get("slice_id") or ""),
                trajectory_ids=tuple(
                    str(trajectory_id)
                    for trajectory_id in item.get("trajectory_ids", ())
                ),
                evaluations=tuple(
                    TrajectoryEvaluation.from_dict(
                        evaluation, trajectory=trajectory_for(evaluation)
                    )
                    for evaluation in item.get("evaluations", ())
                ),
                evaluator_specs=tuple(
                    EvaluatorSpec.from_dict(spec)
                    for spec in item.get("evaluator_specs", ())
                ),
                measurements=tuple(
                    TrajectoryMeasurement.from_dict(
                        measurement, trajectory=trajectory_for(measurement)
                    )
                    for measurement in item.get("measurements", ())
                ),
                measurer_specs=tuple(
                    MeasurerSpec.from_dict(spec)
                    for spec in item.get("measurer_specs", ())
                ),
                annotation_count=(
                    int(item["annotation_count"])
                    if item.get("annotation_count") is not None
                    else None
                ),
                metrics=tuple(
                    Metric.from_dict(metric) for metric in item.get("metrics", ())
                ),
                metadata=dict(item.get("metadata") or {}),
            )

        return cls(
            run_id=str(value["run_id"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            dataset_id=str(value["dataset_id"]),
            dataset_version=str(value.get("dataset_version") or ""),
            slices=tuple(slice_from_dict(item) for item in value.get("slices", ())),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class Metric:
    """One dataset-level value, suitable for comparison and trend reporting."""

    run_id: str
    dataset_id: str
    dataset_slice: str
    name: str
    value: float
    aggregation: MetricAggregation
    unit: str = ""
    direction: MetricDirection = "neutral"
    dataset_version: str = ""
    dimensions: tuple[tuple[str, str], ...] = ()

    @property
    def series_key(self) -> tuple:
        return (
            self.dataset_id,
            self.dataset_slice,
            self.name,
            self.unit,
            self.aggregation,
            self.dimensions,
        )

    @property
    def identity_key(self) -> tuple:
        """Identity within one persisted run; unlike a trend series, includes version."""

        return (self.dataset_version, *self.series_key)

    @property
    def qualified_name(self) -> str:
        suffix = f".{self.aggregation}" if self.aggregation else ""
        dimensions = ",".join(f"{key}={value}" for key, value in self.dimensions)
        return f"{self.name}{suffix}" + (f"{{{dimensions}}}" if dimensions else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "dataset_slice": self.dataset_slice,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "aggregation": self.aggregation,
            "direction": self.direction,
            "dimensions": dict(self.dimensions),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Metric:
        dimensions = value.get("dimensions") or {}
        return cls(
            run_id=str(value["run_id"]),
            dataset_id=str(value["dataset_id"]),
            dataset_version=str(value.get("dataset_version") or ""),
            dataset_slice=str(value.get("dataset_slice") or ""),
            name=str(value["name"]),
            value=float(value["value"]),
            unit=str(value.get("unit") or ""),
            aggregation=value["aggregation"],
            direction=value.get("direction", "neutral"),
            dimensions=tuple((str(key), str(item)) for key, item in dimensions.items()),
        )


def aggregate_metrics(run: TrajectoryEvaluationRun) -> tuple[Metric, ...]:
    """Aggregate all slices in one trajectory evaluation run."""

    return tuple(
        metric
        for slice_ in run.slices
        for metric in _aggregate_slice_metrics(run, slice_)
    )


def _aggregate_slice_metrics(
    run: TrajectoryEvaluationRun, slice_: EvaluationSlice
) -> tuple[Metric, ...]:
    """Aggregate execution facts, evaluations, and measurements for one slice."""

    metrics: list[Metric] = []
    trajectories = _trajectories(slice_)
    metrics.append(
        _metric(run, slice_, "trajectory", len(trajectories), "count", "count")
    )
    executions = [trajectory.execution for trajectory in trajectories]
    known = [
        execution
        for execution in executions
        if execution and execution.outcome != "unknown"
    ]
    if known:
        outcomes = Counter(execution.outcome for execution in known)
        denominator = len(known)
        metrics.extend(
            (
                _metric(
                    run,
                    slice_,
                    "execution.completion",
                    outcomes["completed"] / denominator,
                    "rate",
                    "ratio",
                    "higher_is_better",
                ),
                _metric(
                    run,
                    slice_,
                    "execution.timeout",
                    outcomes["timeout"] / denominator,
                    "rate",
                    "ratio",
                    "lower_is_better",
                ),
                _metric(
                    run,
                    slice_,
                    "execution.failure",
                    (outcomes["failed"] + outcomes["timeout"]) / denominator,
                    "rate",
                    "ratio",
                    "lower_is_better",
                ),
            )
        )
        durations = [
            execution.duration_ms
            for execution in known
            if execution.duration_ms is not None
        ]
        metrics.extend(
            _distribution_metrics(
                run,
                slice_,
                "execution.duration_ms",
                durations,
                "ms",
                "lower_is_better",
                ("mean", "p50", "p95"),
            )
        )

    metrics.extend(_failure_metrics(run, slice_))
    metrics.extend(_evaluation_metrics(run, slice_))
    metrics.extend(_measurement_metrics(run, slice_))
    return tuple(metrics)


def _failure_metrics(
    run: TrajectoryEvaluationRun, slice_: EvaluationSlice
) -> list[Metric]:
    trajectories = _trajectories(slice_)
    total = len(trajectories)
    events: Counter[tuple[str, str, str, str]] = Counter()
    affected: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for trajectory in trajectories:
        for step in trajectory.steps:
            if step.failure:
                key = (
                    "step",
                    step.failure.kind,
                    step.failure.phase,
                    step.failure.error_type,
                )
                events[key] += 1
                affected[key].add(trajectory.trajectory_id)
        if trajectory.execution and trajectory.execution.failure:
            failure = trajectory.execution.failure
            key = ("execution", failure.kind, failure.phase, failure.error_type)
            events[key] += 1
            affected[key].add(trajectory.trajectory_id)

    result = []
    for key, count in sorted(events.items()):
        impact, kind, phase, error_type = key
        dimensions = (
            ("impact", impact),
            ("kind", kind),
            ("phase", phase),
            ("error_type", error_type),
        )
        result.append(
            _metric(
                run,
                slice_,
                "failure",
                count,
                "count",
                "count",
                "lower_is_better",
                dimensions,
            )
        )
        if total:
            result.append(
                _metric(
                    run,
                    slice_,
                    "failure",
                    len(affected[key]) / total,
                    "rate",
                    "ratio",
                    "lower_is_better",
                    dimensions,
                )
            )
    return result


def _trajectories(slice_: EvaluationSlice) -> tuple[Trajectory, ...]:
    by_id = {
        item.trajectory.trajectory_id: item.trajectory
        for item in (*slice_.evaluations, *slice_.measurements)
    }
    return tuple(by_id.values())


def _run_trajectories(run: TrajectoryEvaluationRun) -> tuple[Trajectory, ...]:
    by_id = {
        trajectory.trajectory_id: trajectory
        for slice_ in run.slices
        for trajectory in _trajectories(slice_)
    }
    return tuple(by_id.values())


def _slice_to_dict(slice_: EvaluationSlice) -> dict[str, Any]:
    return {
        "slice_id": slice_.slice_id,
        "trajectory_ids": list(slice_.trajectory_ids),
        "evaluations": [item.to_dict() for item in slice_.evaluations],
        "evaluator_specs": [item.to_dict() for item in slice_.evaluator_specs],
        "measurements": [item.to_dict() for item in slice_.measurements],
        "measurer_specs": [item.to_dict() for item in slice_.measurer_specs],
        "annotation_count": slice_.annotation_count,
        "metrics": [item.to_dict() for item in slice_.metrics],
        "metadata": dict(slice_.metadata),
    }


def _evaluation_metrics(
    run: TrajectoryEvaluationRun, slice_: EvaluationSlice
) -> list[Metric]:
    result = []
    specs = {spec.evaluator_id: spec for spec in slice_.evaluator_specs}
    by_evaluator = {
        evaluator_id: [
            evaluation
            for item in slice_.evaluations
            for evaluation in item.results
            if evaluation.evaluator_id == evaluator_id
        ]
        for evaluator_id in specs
    }
    for evaluator_id in specs:
        evaluations = by_evaluator[evaluator_id]
        total = len(slice_.trajectory_ids)
        evaluated = [item for item in evaluations if item.status == "evaluated"]
        errors = [item for item in evaluations if item.status == "error"]
        dimensions = (("evaluator_id", evaluator_id),)
        if total:
            result.extend(
                (
                    _metric(
                        run,
                        slice_,
                        "evaluation.applicability",
                        len(evaluated) / total,
                        "rate",
                        "ratio",
                        "neutral",
                        dimensions,
                    ),
                    _metric(
                        run,
                        slice_,
                        "evaluation.error",
                        len(errors) / total,
                        "rate",
                        "ratio",
                        "lower_is_better",
                        dimensions,
                    ),
                )
            )
        if evaluated:
            judged = [item for item in evaluated if item.verdict is not None]
            if judged:
                passing = sum(item.verdict == "pass" for item in judged)
                result.append(
                    _metric(
                        run,
                        slice_,
                        "evaluation.pass",
                        passing / len(judged),
                        "rate",
                        "ratio",
                        "higher_is_better",
                        dimensions,
                    )
                )
            scores = [item.score for item in evaluated if item.score is not None]
            result.extend(
                _distribution_metrics(
                    run,
                    slice_,
                    "evaluation.score",
                    scores,
                    "score",
                    "higher_is_better",
                    ("mean",),
                    dimensions,
                )
            )

    return result


def _measurement_metrics(
    run: TrajectoryEvaluationRun, slice_: EvaluationSlice
) -> list[Metric]:
    result = []
    specs = {spec.measurer_id: spec for spec in slice_.measurer_specs}
    by_measurer = {
        measurer_id: [
            measurement
            for item in slice_.measurements
            for measurement in item.results
            if measurement.measurer_id == measurer_id
        ]
        for measurer_id in specs
    }
    for measurer_id, spec in specs.items():
        measurements = by_measurer[measurer_id]
        total = len(slice_.trajectory_ids)
        measured = [item for item in measurements if item.status == "measured"]
        errors = [item for item in measurements if item.status == "error"]
        dimensions = (("measurer_id", measurer_id),)
        if total:
            result.extend(
                (
                    _metric(
                        run,
                        slice_,
                        "measurement.applicability",
                        len(measured) / total,
                        "rate",
                        "ratio",
                        "neutral",
                        dimensions,
                    ),
                    _metric(
                        run,
                        slice_,
                        "measurement.error",
                        len(errors) / total,
                        "rate",
                        "ratio",
                        "lower_is_better",
                        dimensions,
                    ),
                )
            )

        for measurement_spec in spec.measurements:
            values = [
                float(item.measurements[measurement_spec.name])
                for item in measured
                if measurement_spec.name in item.measurements
            ]
            result.extend(
                _distribution_metrics(
                    run,
                    slice_,
                    "measurement.value",
                    values,
                    measurement_spec.unit,
                    measurement_spec.direction,
                    measurement_spec.aggregations,
                    (
                        ("measurer_id", measurer_id),
                        ("measurement", measurement_spec.name),
                    ),
                )
            )
    return result


def _distribution_metrics(
    run: TrajectoryEvaluationRun,
    slice_: EvaluationSlice,
    name: str,
    values: Iterable[float],
    unit: str,
    direction: MetricDirection,
    aggregations: tuple[MetricAggregation, ...],
    dimensions: tuple[tuple[str, str], ...] = (),
) -> list[Metric]:
    collected = list(values)
    if not collected:
        return []
    result = []
    for aggregation in aggregations:
        if aggregation == "sum":
            value = sum(collected)
        elif aggregation == "mean":
            value = sum(collected) / len(collected)
        elif aggregation == "p50":
            value = _percentile(collected, 0.50)
        elif aggregation == "p95":
            value = _percentile(collected, 0.95)
        else:
            continue
        result.append(
            _metric(
                run,
                slice_,
                name,
                value,
                aggregation,
                unit,
                direction,
                dimensions,
            )
        )
    return result


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _metric(
    run: TrajectoryEvaluationRun,
    slice_: EvaluationSlice,
    name: str,
    value: float,
    aggregation: MetricAggregation,
    unit: str = "",
    direction: MetricDirection = "neutral",
    dimensions: tuple[tuple[str, str], ...] = (),
) -> Metric:
    return Metric(
        run_id=run.run_id,
        dataset_id=run.dataset_id,
        dataset_version=run.dataset_version,
        dataset_slice=slice_.slice_id,
        name=name,
        value=round(float(value), 6),
        unit=unit,
        aggregation=aggregation,
        direction=direction,
        dimensions=dimensions,
    )
