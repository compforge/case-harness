"""Canonical trajectory IR.

The message dictionaries intentionally follow OTel GenAI's role + parts schema instead
of introducing another message class.  ``Step`` adds only execution identity, ordering,
timing, and parentage around those standard messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Step:
    """One ordered agent operation, normally projected from one GenAI span."""

    step_id: str
    parent_step_id: str | None
    operation: str
    name: str
    start_ms: float
    duration_ms: float
    status: str = ""
    input_messages: tuple[dict[str, Any], ...] = ()
    output_messages: tuple[dict[str, Any], ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "parent_step_id": self.parent_step_id,
            "operation": self.operation,
            "name": self.name,
            "start_ms": self.start_ms,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "input_messages": list(self.input_messages),
            "output_messages": list(self.output_messages),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Step:
        return cls(
            step_id=value["step_id"],
            parent_step_id=value.get("parent_step_id"),
            operation=value.get("operation", ""),
            name=value.get("name", ""),
            start_ms=float(value.get("start_ms", 0)),
            duration_ms=float(value.get("duration_ms", 0)),
            status=value.get("status", ""),
            input_messages=tuple(value.get("input_messages", ())),
            output_messages=tuple(value.get("output_messages", ())),
            attributes=dict(value.get("attributes", {})),
        )


@dataclass(frozen=True, slots=True)
class Trajectory:
    """An ordered decision/action history for one agent or workflow invocation."""

    trajectory_id: str
    steps: tuple[Step, ...]
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "source": self.source,
            "metadata": dict(self.metadata),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Trajectory:
        return cls(
            trajectory_id=value["trajectory_id"],
            source=value.get("source", ""),
            metadata=dict(value.get("metadata", {})),
            steps=tuple(Step.from_dict(step) for step in value.get("steps", ())),
        )
