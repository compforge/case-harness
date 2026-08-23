"""Recording source contract: discover and fetch raw trajectory recordings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class RecordingQuery:
    """Portable filters for selecting recording references.

    ``started_at_or_after`` is inclusive and ``started_before`` is exclusive.
    Attributes use exact-match semantics. Source implementations may expose
    additional domain-specific filters outside this common contract.
    """

    started_at_or_after: datetime | None = None
    started_before: datetime | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit <= 0:
            raise ValueError("recording query limit must be positive")


@dataclass(frozen=True)
class RecordingRef:
    """Stable identity and cheap provenance for one external recording."""

    recording_id: str
    uri: str
    started_at: datetime | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "uri": self.uri,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class Recording:
    """Fetched raw recording content plus its selected reference."""

    ref: RecordingRef
    text: str


@runtime_checkable
class RecordingSource(Protocol):
    """Discover recording metadata cheaply, then fetch selected raw content."""

    def select(self, query: RecordingQuery | None = None) -> list[RecordingRef]: ...

    def fetch(self, ref: RecordingRef) -> Recording: ...
