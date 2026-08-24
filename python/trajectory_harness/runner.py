"""Evaluate and measure one fixed trajectory dataset."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from trajectory_harness.dataset import TrajectoryDataset
from trajectory_harness.evaluate import Evaluator, EvaluatorSpec, evaluate
from trajectory_harness.measure import Measurer, MeasurerSpec, measure
from trajectory_harness.metrics import (
    DatasetRef,
    EvaluationRun,
    Metric,
    aggregate_metrics,
)
from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class TrajectoryRun:
    """One execution of evaluator/measurer suites against one dataset version."""

    run_id: str
    created_at: datetime
    dataset_id: str
    dataset_version: str
    evaluations: tuple[EvaluationRun, ...]
    metrics: tuple[Metric, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class TrajectoryEvaluationRunner:
    """Dataset-to-run stage, independent of source collection and report rendering."""

    def __init__(
        self,
        *,
        evaluators: Sequence[Evaluator] = (),
        measurers: Sequence[Measurer] = (),
    ) -> None:
        self.evaluators = tuple(evaluators)
        self.measurers = tuple(measurers)

    def slice_for(self, trajectory: Trajectory, dataset: TrajectoryDataset) -> str:
        """Return the comparison slice for a trajectory."""

        return ""

    def evaluators_for(self, dataset: DatasetRef) -> Sequence[Evaluator]:
        return self.evaluators

    def measurers_for(self, dataset: DatasetRef) -> Sequence[Measurer]:
        return self.measurers

    def metadata_for(
        self,
        dataset: DatasetRef,
        trajectories: Sequence[Trajectory],
        source_dataset: TrajectoryDataset,
    ) -> Mapping[str, Any]:
        return {}

    def run(
        self,
        dataset: TrajectoryDataset,
        *,
        run_id: str,
        created_at: datetime | None = None,
    ) -> TrajectoryRun:
        timestamp = created_at or datetime.now(timezone.utc)
        grouped: dict[str, list[Trajectory]] = defaultdict(list)
        for trajectory in dataset.trajectories:
            grouped[self.slice_for(trajectory, dataset)].append(trajectory)

        evaluations = []
        for dataset_slice in sorted(grouped):
            trajectories = tuple(grouped[dataset_slice])
            dataset_ref = DatasetRef(
                dataset_id=dataset.dataset_id,
                version=dataset.version,
                slice=dataset_slice,
                sample_count=_sample_count(dataset, trajectories),
            )
            evaluators = tuple(self.evaluators_for(dataset_ref))
            measurers = tuple(self.measurers_for(dataset_ref))
            evaluations.append(
                EvaluationRun(
                    run_id=run_id,
                    created_at=timestamp,
                    dataset=dataset_ref,
                    items=tuple(
                        evaluate(trajectory, evaluators) for trajectory in trajectories
                    ),
                    evaluator_specs=_evaluator_specs(evaluators),
                    measurement_items=tuple(
                        measure(trajectory, measurers) for trajectory in trajectories
                    ),
                    measurer_specs=_measurer_specs(measurers),
                    metadata=dict(
                        self.metadata_for(dataset_ref, trajectories, dataset)
                    ),
                )
            )

        evaluation_tuple = tuple(evaluations)
        return TrajectoryRun(
            run_id=run_id,
            created_at=timestamp,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            evaluations=evaluation_tuple,
            metrics=tuple(
                metric
                for evaluation in evaluation_tuple
                for metric in aggregate_metrics(evaluation)
            ),
        )


def _sample_count(
    dataset: TrajectoryDataset, trajectories: Sequence[Trajectory]
) -> int:
    if not dataset.samples:
        return len(trajectories)
    trajectory_ids = {item.trajectory_id for item in trajectories}
    return sum(
        bool(trajectory_ids.intersection(sample.trajectory_ids))
        for sample in dataset.samples
    )


def _evaluator_specs(evaluators: Sequence[Evaluator]) -> tuple[EvaluatorSpec, ...]:
    return tuple({item.spec.evaluator_id: item.spec for item in evaluators}.values())


def _measurer_specs(measurers: Sequence[Measurer]) -> tuple[MeasurerSpec, ...]:
    return tuple({item.spec.measurer_id: item.spec for item in measurers}.values())
