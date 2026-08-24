"""Build a fixed trajectory dataset from external recordings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Sequence

from trajectory_harness.dataset import TrajectoryDataset
from trajectory_harness.loaders.base import TrajectoryLoader
from trajectory_harness.model import Trajectory
from trajectory_harness.source import RecordingQuery, RecordingRef, RecordingSource

DatasetBuildPhase = Literal["fetch", "load"]


@dataclass(frozen=True, slots=True)
class DatasetIssue:
    """One source recording that could not enter the fixed dataset."""

    recording_id: str
    uri: str
    phase: DatasetBuildPhase
    error: str

    def to_dict(self) -> dict[str, str]:
        return {
            "recording_id": self.recording_id,
            "uri": self.uri,
            "phase": self.phase,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DatasetIssue:
        return cls(
            recording_id=str(value["recording_id"]),
            uri=str(value.get("uri") or ""),
            phase=value["phase"],
            error=str(value.get("error") or ""),
        )


@dataclass(frozen=True, slots=True)
class DatasetBuildSummary:
    """Collection provenance and health stored with a trajectory dataset."""

    selected_recordings: int = 0
    fetched_recordings: int = 0
    loaded_trajectories: int = 0
    included_trajectories: int = 0
    included_samples: int = 0
    unmatched_samples: int = 0
    query: dict[str, Any] = field(default_factory=dict)
    issues: tuple[DatasetIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_recordings": self.selected_recordings,
            "fetched_recordings": self.fetched_recordings,
            "loaded_trajectories": self.loaded_trajectories,
            "included_trajectories": self.included_trajectories,
            "included_samples": self.included_samples,
            "unmatched_samples": self.unmatched_samples,
            "query": dict(self.query),
            "issues": [item.to_dict() for item in self.issues],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DatasetBuildSummary:
        return cls(
            selected_recordings=int(value.get("selected_recordings", 0)),
            fetched_recordings=int(value.get("fetched_recordings", 0)),
            loaded_trajectories=int(value.get("loaded_trajectories", 0)),
            included_trajectories=int(value.get("included_trajectories", 0)),
            included_samples=int(value.get("included_samples", 0)),
            unmatched_samples=int(value.get("unmatched_samples", 0)),
            query=dict(value.get("query") or {}),
            issues=tuple(
                DatasetIssue.from_dict(item) for item in value.get("issues", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    dataset: TrajectoryDataset
    summary: DatasetBuildSummary


class TrajectoryDatasetBuilder(ABC):
    """Reusable Source/Loader boundary; domains own label joins in ``assemble``."""

    def __init__(self, *, source: RecordingSource, loader: TrajectoryLoader) -> None:
        self.source = source
        self.loader = loader

    @abstractmethod
    def assemble(
        self,
        recordings: Sequence[RecordingRef],
        trajectories: Sequence[Trajectory],
        query: RecordingQuery | None,
    ) -> TrajectoryDataset:
        """Join domain labels and construct the versioned dataset."""

    def build(self, query: RecordingQuery | None = None) -> DatasetBuildResult:
        refs = self.source.select(query)
        recordings: list[RecordingRef] = []
        trajectories: list[Trajectory] = []
        issues: list[DatasetIssue] = []
        fetched = 0
        loaded = 0
        for ref in refs:
            try:
                recording = self.source.fetch(ref)
                fetched += 1
            except Exception as error:  # source plugins are an isolation boundary
                issues.append(_issue(ref, "fetch", error))
                continue
            try:
                loaded_trajectories = tuple(
                    self.loader.loads(recording.text, source=recording.ref.uri)
                )
                loaded += len(loaded_trajectories)
            except Exception as error:  # loaders isolate source-specific formats
                issues.append(_issue(ref, "load", error))
                continue
            recordings.append(recording.ref)
            trajectories.extend(
                replace(item, recording_id=recording.ref.recording_id)
                for item in loaded_trajectories
            )

        dataset = self.assemble(tuple(recordings), tuple(trajectories), query)
        return DatasetBuildResult(
            dataset=dataset,
            summary=DatasetBuildSummary(
                selected_recordings=len(refs),
                fetched_recordings=fetched,
                loaded_trajectories=loaded,
                included_trajectories=len(dataset.trajectories),
                included_samples=len(dataset.samples),
                unmatched_samples=sum(
                    not sample.trajectory_ids for sample in dataset.samples
                ),
                query=query.to_dict() if query else {},
                issues=tuple(issues),
            ),
        )


def _issue(
    ref: RecordingRef, phase: DatasetBuildPhase, error: Exception
) -> DatasetIssue:
    return DatasetIssue(
        recording_id=ref.recording_id,
        uri=ref.uri,
        phase=phase,
        error=f"{type(error).__name__}: {error}",
    )
