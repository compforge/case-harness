"""Versioned trajectory dataset and annotation model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class TrajectorySample:
    """One labeled unit that joins domain annotation to recorded trajectories.

    A sample may reference multiple trajectories (for example, multiple review stages).
    An empty ``trajectory_ids`` is allowed so a dataset can retain a known label whose
    recording produced no usable trajectory.
    """

    sample_id: str
    recording_id: str
    trajectory_ids: tuple[str, ...] = ()
    annotation: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "recording_id": self.recording_id,
            "trajectory_ids": list(self.trajectory_ids),
            "annotation": dict(self.annotation),
            "dimensions": dict(self.dimensions),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrajectorySample:
        return cls(
            sample_id=str(value["sample_id"]),
            recording_id=str(value["recording_id"]),
            trajectory_ids=tuple(str(item) for item in value.get("trajectory_ids", ())),
            annotation=dict(value.get("annotation") or {}),
            dimensions={
                str(key): str(item)
                for key, item in (value.get("dimensions") or {}).items()
            },
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class TrajectoryDataset:
    """A fixed, versioned input to trajectory evaluation."""

    dataset_id: str
    version: str
    trajectories: tuple[Trajectory, ...]
    samples: tuple[TrajectorySample, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("trajectory dataset needs a dataset_id")

        trajectories: dict[str, str] = {}
        for trajectory in self.trajectories:
            trajectory_id = trajectory.trajectory_id
            if trajectory_id in trajectories:
                raise ValueError(f"duplicate trajectory_id {trajectory_id!r}")
            trajectories[trajectory_id] = trajectory.recording_id

        sample_ids: set[str] = set()
        for sample in self.samples:
            if sample.sample_id in sample_ids:
                raise ValueError(f"duplicate sample_id {sample.sample_id!r}")
            sample_ids.add(sample.sample_id)
            for trajectory_id in sample.trajectory_ids:
                owner = trajectories.get(trajectory_id)
                if owner is None:
                    raise ValueError(
                        f"sample {sample.sample_id!r} references unknown trajectory "
                        f"{trajectory_id!r}"
                    )
                if owner != sample.recording_id:
                    raise ValueError(
                        f"sample {sample.sample_id!r} references trajectory "
                        f"{trajectory_id!r} from recording {owner!r}"
                    )

    @property
    def trajectory_by_id(self) -> dict[str, Trajectory]:
        return {item.trajectory_id: item for item in self.trajectories}

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "trajectories": [item.to_dict() for item in self.trajectories],
            "samples": [item.to_dict() for item in self.samples],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrajectoryDataset:
        return cls(
            dataset_id=str(value["dataset_id"]),
            version=str(value.get("version") or ""),
            trajectories=tuple(
                Trajectory.from_dict(item) for item in value.get("trajectories", ())
            ),
            samples=tuple(
                TrajectorySample.from_dict(item) for item in value.get("samples", ())
            ),
            metadata=dict(value.get("metadata") or {}),
        )
