"""Evaluate and measure one fixed trajectory dataset."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from trajectory_harness.dataset import TrajectoryDataset
from trajectory_harness.evaluate import Evaluator, EvaluatorSpec, evaluate
from trajectory_harness.measure import Measurer, MeasurerSpec, measure
from trajectory_harness.metrics import (
    EvaluationSlice,
    TrajectoryEvaluationRun,
    aggregate_metrics,
)
from trajectory_harness.model import Trajectory


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

    def evaluators_for(
        self, slice_id: str, dataset: TrajectoryDataset
    ) -> Sequence[Evaluator]:
        return self.evaluators

    def measurers_for(
        self, slice_id: str, dataset: TrajectoryDataset
    ) -> Sequence[Measurer]:
        return self.measurers

    def metadata_for(
        self,
        slice_id: str,
        trajectories: Sequence[Trajectory],
        dataset: TrajectoryDataset,
    ) -> Mapping[str, Any]:
        return {}

    def run(
        self,
        dataset: TrajectoryDataset,
        *,
        run_id: str,
        created_at: datetime | None = None,
    ) -> TrajectoryEvaluationRun:
        timestamp = created_at or datetime.now(timezone.utc)
        grouped: dict[str, list[Trajectory]] = defaultdict(list)
        for trajectory in dataset.trajectories:
            grouped[self.slice_for(trajectory, dataset)].append(trajectory)

        slices = []
        for slice_id in sorted(grouped):
            trajectories = tuple(grouped[slice_id])
            evaluators = tuple(self.evaluators_for(slice_id, dataset))
            measurers = tuple(self.measurers_for(slice_id, dataset))
            slices.append(
                EvaluationSlice(
                    slice_id=slice_id,
                    trajectory_ids=tuple(
                        trajectory.trajectory_id for trajectory in trajectories
                    ),
                    evaluations=tuple(
                        evaluate(trajectory, evaluators) for trajectory in trajectories
                    ),
                    evaluator_specs=_evaluator_specs(evaluators),
                    measurements=tuple(
                        measure(trajectory, measurers) for trajectory in trajectories
                    ),
                    measurer_specs=_measurer_specs(measurers),
                    annotation_count=_annotation_count(dataset, trajectories),
                    metadata=dict(self.metadata_for(slice_id, trajectories, dataset)),
                )
            )

        run = TrajectoryEvaluationRun(
            run_id=run_id,
            created_at=timestamp,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            slices=tuple(slices),
        )
        return replace(
            run,
            slices=tuple(
                replace(
                    slice_,
                    metrics=aggregate_metrics(replace(run, slices=(slice_,))),
                )
                for slice_ in run.slices
            ),
        )


def _annotation_count(
    dataset: TrajectoryDataset, trajectories: Sequence[Trajectory]
) -> int:
    if not dataset.annotations:
        return 0
    trajectory_ids = {item.trajectory_id for item in trajectories}
    return sum(
        bool(trajectory_ids.intersection(annotation.trajectory_ids))
        for annotation in dataset.annotations
    )


def _evaluator_specs(evaluators: Sequence[Evaluator]) -> tuple[EvaluatorSpec, ...]:
    return tuple({item.spec.evaluator_id: item.spec for item in evaluators}.values())


def _measurer_specs(measurers: Sequence[Measurer]) -> tuple[MeasurerSpec, ...]:
    return tuple({item.spec.measurer_id: item.spec for item in measurers}.values())
