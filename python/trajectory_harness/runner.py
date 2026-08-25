"""Evaluate and measure one fixed trajectory dataset."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from trajectory_harness.dataset import TrajectoryDataset
from trajectory_harness.detect import Detector, DetectorSpec, detect
from trajectory_harness.evaluate import Evaluator, EvaluatorSpec, evaluate
from trajectory_harness.measure import Measurer, MeasurerSpec, measure
from trajectory_harness.metrics import TrajectoryEvaluationRun, aggregate_metrics
from trajectory_harness.model import Trajectory


class TrajectoryEvaluationRunner:
    """Dataset-to-run stage, independent of source collection and report rendering."""

    def __init__(
        self,
        *,
        detectors: Sequence[Detector] = (),
        evaluators: Sequence[Evaluator] = (),
        measurers: Sequence[Measurer] = (),
    ) -> None:
        self.detectors = tuple(detectors)
        self.evaluators = tuple(evaluators)
        self.measurers = tuple(measurers)

    def target_for(self, trajectory: Trajectory, dataset: TrajectoryDataset) -> str:
        """Return the domain target represented by one Worksheet row."""

        return ""

    def detectors_for(
        self, target: str, dataset: TrajectoryDataset
    ) -> Sequence[Detector]:
        return self.detectors

    def evaluators_for(
        self, target: str, dataset: TrajectoryDataset
    ) -> Sequence[Evaluator]:
        return self.evaluators

    def measurers_for(
        self, target: str, dataset: TrajectoryDataset
    ) -> Sequence[Measurer]:
        return self.measurers

    def metadata_for(self, dataset: TrajectoryDataset) -> Mapping[str, Any]:
        return {}

    def run(
        self,
        dataset: TrajectoryDataset,
        *,
        run_id: str,
        created_at: datetime | None = None,
    ) -> TrajectoryEvaluationRun:
        timestamp = created_at or datetime.now(timezone.utc)
        targets = tuple(
            (
                trajectory.trajectory_id,
                self.target_for(trajectory, dataset),
            )
            for trajectory in dataset.trajectories
        )
        detections = []
        evaluations = []
        measurements = []
        selected_detectors = []
        selected_evaluators = []
        selected_measurers = []
        for trajectory, (_, target) in zip(dataset.trajectories, targets):
            detectors = tuple(self.detectors_for(target, dataset))
            evaluators = tuple(self.evaluators_for(target, dataset))
            measurers = tuple(self.measurers_for(target, dataset))
            selected_detectors.extend(detectors)
            selected_evaluators.extend(evaluators)
            selected_measurers.extend(measurers)
            for category, items in _detectors_by_category(detectors):
                detections.append(
                    detect(
                        trajectory,
                        items,
                        target=target,
                        category=category,
                    )
                )
            for category, items in _evaluators_by_category(evaluators):
                evaluations.append(
                    evaluate(
                        trajectory,
                        items,
                        target=target,
                        category=category,
                    )
                )
            for category, items in _measurers_by_category(measurers):
                measurements.append(
                    measure(
                        trajectory,
                        items,
                        target=target,
                        category=category,
                    )
                )

        run = TrajectoryEvaluationRun(
            run_id=run_id,
            created_at=timestamp,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            trajectory_ids=tuple(item.trajectory_id for item in dataset.trajectories),
            trajectory_targets=targets,
            detections=tuple(detections),
            detector_specs=_detector_specs(selected_detectors),
            evaluations=tuple(evaluations),
            evaluator_specs=_evaluator_specs(selected_evaluators),
            measurements=tuple(measurements),
            measurer_specs=_measurer_specs(selected_measurers),
            annotation_count=_annotation_count(dataset, dataset.trajectories),
            metadata=dict(self.metadata_for(dataset)),
        )
        return replace(
            run,
            metrics=aggregate_metrics(run, trajectories=dataset.trajectories),
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


def _detector_specs(detectors: Sequence[Detector]) -> tuple[DetectorSpec, ...]:
    return tuple({item.spec.detector_id: item.spec for item in detectors}.values())


def _measurer_specs(measurers: Sequence[Measurer]) -> tuple[MeasurerSpec, ...]:
    return tuple({item.spec.measurer_id: item.spec for item in measurers}.values())


def _detectors_by_category(
    detectors: Sequence[Detector],
) -> tuple[tuple[str, tuple[Detector, ...]], ...]:
    categories: dict[str, list[Detector]] = {}
    for detector in detectors:
        categories.setdefault(detector.spec.category, []).append(detector)
    return tuple(
        (category, tuple(items)) for category, items in sorted(categories.items())
    )


def _evaluators_by_category(
    evaluators: Sequence[Evaluator],
) -> tuple[tuple[str, tuple[Evaluator, ...]], ...]:
    categories: dict[str, list[Evaluator]] = {}
    for evaluator in evaluators:
        categories.setdefault(evaluator.spec.category, []).append(evaluator)
    return tuple(
        (category, tuple(items)) for category, items in sorted(categories.items())
    )


def _measurers_by_category(
    measurers: Sequence[Measurer],
) -> tuple[tuple[str, tuple[Measurer, ...]], ...]:
    categories: dict[str, list[Measurer]] = {}
    for measurer in measurers:
        categories.setdefault(measurer.spec.category, []).append(measurer)
    return tuple(
        (category, tuple(items)) for category, items in sorted(categories.items())
    )
