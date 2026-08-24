"""Independent dataset/run artifacts for offline evaluation and report rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from trajectory_harness.build import DatasetBuildResult, DatasetBuildSummary
from trajectory_harness.dataset import TrajectoryDataset
from trajectory_harness.evaluate import EvaluatorSpec, TrajectoryEvaluation
from trajectory_harness.measure import MeasurerSpec, TrajectoryMeasurement
from trajectory_harness.metrics import DatasetRef, EvaluationRun, Metric
from trajectory_harness.model import Trajectory
from trajectory_harness.runner import TrajectoryRun

DATASET_SCHEMA = 1
RUN_SCHEMA = 1
DATASET_FILE = "dataset.json"
RUN_FILE = "run.json"


@dataclass(frozen=True, slots=True)
class TrajectoryRunArtifact:
    """The fixed dataset plus one evaluation run over that exact version."""

    build: DatasetBuildResult
    run: TrajectoryRun

    def __post_init__(self) -> None:
        dataset = self.build.dataset
        identity = (dataset.dataset_id, dataset.version)
        if (self.run.dataset_id, self.run.dataset_version) != identity:
            raise ValueError("trajectory run does not match its dataset artifact")
        for evaluation in self.run.evaluations:
            if (evaluation.dataset.dataset_id, evaluation.dataset.version) != identity:
                raise ValueError("evaluation slice does not match its trajectory run")
            if (evaluation.run_id, evaluation.created_at) != (
                self.run.run_id,
                self.run.created_at,
            ):
                raise ValueError("evaluation slice does not match its enclosing run")
        for metric in self.run.metrics:
            if (metric.dataset_id, metric.dataset_version) != identity:
                raise ValueError("metric does not match its trajectory run")
            if metric.run_id != self.run.run_id:
                raise ValueError("metric does not match its enclosing run")

    @property
    def dataset(self) -> TrajectoryDataset:
        return self.build.dataset


def write_run_artifact(
    run_dir: str | Path, artifact: TrajectoryRunArtifact
) -> tuple[Path, Path]:
    """Persist one dataset and one current run; history is deliberately external."""

    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dataset_path = write_dataset_artifact(directory, artifact.build)
    run_path = _write_json(directory / RUN_FILE, _run_to_dict(artifact.run))
    return dataset_path, run_path


def write_dataset_artifact(directory: str | Path, build: DatasetBuildResult) -> Path:
    """Persist a dataset independently so later runs need no recording source."""

    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    return _write_json(
        target_dir / DATASET_FILE,
        {
            "schema": DATASET_SCHEMA,
            "dataset": build.dataset.to_dict(),
            "build": build.summary.to_dict(),
        },
    )


def load_dataset_artifact(directory: str | Path) -> DatasetBuildResult:
    """Load a fixed dataset independently of any prior evaluation run."""

    dataset_value = json.loads(
        (Path(directory) / DATASET_FILE).read_text(encoding="utf-8")
    )
    if dataset_value.get("schema") != DATASET_SCHEMA:
        raise ValueError(
            "unsupported trajectory dataset schema "
            f"{dataset_value.get('schema')!r}; expected {DATASET_SCHEMA}"
        )
    dataset = TrajectoryDataset.from_dict(dataset_value["dataset"])
    return DatasetBuildResult(
        dataset=dataset,
        summary=DatasetBuildSummary.from_dict(dataset_value.get("build") or {}),
    )


def load_run_artifact(run_dir: str | Path) -> TrajectoryRunArtifact:
    """Load one run without touching a Source, Loader, Evaluator, or Measurer."""

    directory = Path(run_dir)
    build = load_dataset_artifact(directory)
    dataset = build.dataset
    run_value = json.loads((directory / RUN_FILE).read_text(encoding="utf-8"))
    run = _run_from_dict(run_value, dataset.trajectory_by_id)
    return TrajectoryRunArtifact(build=build, run=run)


def _run_to_dict(run: TrajectoryRun) -> dict[str, Any]:
    return {
        "schema": RUN_SCHEMA,
        "run_id": run.run_id,
        "created_at": run.created_at.isoformat(),
        "dataset_id": run.dataset_id,
        "dataset_version": run.dataset_version,
        "evaluations": [_evaluation_to_dict(item) for item in run.evaluations],
        "metrics": [item.to_dict() for item in run.metrics],
        "metadata": dict(run.metadata),
    }


def _run_from_dict(
    value: dict[str, Any], trajectories: dict[str, Trajectory]
) -> TrajectoryRun:
    if value.get("schema") != RUN_SCHEMA:
        raise ValueError(
            f"unsupported trajectory run schema {value.get('schema')!r}; "
            f"expected {RUN_SCHEMA}"
        )
    run_id = str(value["run_id"])
    created_at = datetime.fromisoformat(str(value["created_at"]))
    evaluations = tuple(
        replace(
            _evaluation_from_dict(item, trajectories),
            run_id=run_id,
            created_at=created_at,
        )
        for item in value.get("evaluations", ())
    )
    return TrajectoryRun(
        run_id=run_id,
        created_at=created_at,
        dataset_id=str(value["dataset_id"]),
        dataset_version=str(value.get("dataset_version") or ""),
        evaluations=evaluations,
        metrics=tuple(Metric.from_dict(item) for item in value.get("metrics", ())),
        metadata=dict(value.get("metadata") or {}),
    )


def _evaluation_to_dict(run: EvaluationRun) -> dict[str, Any]:
    return {
        "dataset": run.dataset.to_dict(),
        "items": [item.to_dict() for item in run.items],
        "evaluator_specs": [item.to_dict() for item in run.evaluator_specs],
        "measurement_items": [item.to_dict() for item in run.measurement_items],
        "measurer_specs": [item.to_dict() for item in run.measurer_specs],
        "metadata": dict(run.metadata),
    }


def _evaluation_from_dict(
    value: dict[str, Any], trajectories: dict[str, Trajectory]
) -> EvaluationRun:
    def trajectory_for(item: dict[str, Any]) -> Trajectory:
        trajectory_id = str(item["trajectory_id"])
        try:
            return trajectories[trajectory_id]
        except KeyError as error:
            raise ValueError(
                f"run item references unknown trajectory {trajectory_id!r}"
            ) from error

    return EvaluationRun(
        run_id="",
        created_at=datetime.min,
        dataset=DatasetRef.from_dict(value["dataset"]),
        items=tuple(
            TrajectoryEvaluation.from_dict(item, trajectory=trajectory_for(item))
            for item in value.get("items", ())
        ),
        evaluator_specs=tuple(
            EvaluatorSpec.from_dict(item) for item in value.get("evaluator_specs", ())
        ),
        measurement_items=tuple(
            TrajectoryMeasurement.from_dict(item, trajectory=trajectory_for(item))
            for item in value.get("measurement_items", ())
        ),
        measurer_specs=tuple(
            MeasurerSpec.from_dict(item) for item in value.get("measurer_specs", ())
        ),
        metadata=dict(value.get("metadata") or {}),
    )


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path
