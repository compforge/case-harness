"""Canonical trajectory IR.

The message dictionaries intentionally follow OTel GenAI's role + parts schema instead
of introducing another message class.  ``Step`` adds only execution identity, ordering,
timing, and parentage around those standard messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FailureKind = Literal["llm", "tool", "agent", "workflow", "unknown"]
ExecutionOutcome = Literal["completed", "failed", "timeout", "canceled", "unknown"]


@dataclass(frozen=True, slots=True)
class Failure:
    """One normalized operation failure.

    ``kind`` identifies the operation family, ``phase`` narrows where it failed,
    and ``error_type`` is the reusable low-cardinality failure class.  The full
    grouping key (for example ``llm.request.timeout``) is derived, not persisted.
    """

    kind: FailureKind
    phase: str
    error_type: str
    code: str = ""
    message: str = ""

    @property
    def key(self) -> str:
        return ".".join(
            part for part in (self.kind, self.phase, self.error_type) if part
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "phase": self.phase,
            "error_type": self.error_type,
            "code": self.code,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Failure:
        return cls(
            kind=value.get("kind", "unknown"),
            phase=str(value.get("phase") or ""),
            error_type=str(value.get("error_type") or "unknown"),
            code=str(value.get("code") or ""),
            message=str(value.get("message") or ""),
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Authoritative final outcome of one trajectory execution."""

    outcome: ExecutionOutcome
    duration_ms: float | None = None
    failure: Failure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
            "failure": self.failure.to_dict() if self.failure else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExecutionResult:
        raw_failure = value.get("failure")
        return cls(
            outcome=value.get("outcome", "unknown"),
            duration_ms=(
                float(value["duration_ms"])
                if value.get("duration_ms") is not None
                else None
            ),
            failure=(
                Failure.from_dict(raw_failure)
                if isinstance(raw_failure, dict)
                else None
            ),
        )


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
    failure: Failure | None = None
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
            "failure": self.failure.to_dict() if self.failure else None,
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
            failure=(
                Failure.from_dict(value["failure"])
                if isinstance(value.get("failure"), dict)
                else None
            ),
            input_messages=tuple(value.get("input_messages", ())),
            output_messages=tuple(value.get("output_messages", ())),
            attributes=dict(value.get("attributes", {})),
        )


@dataclass(frozen=True, slots=True)
class Trajectory:
    """An ordered decision/action history for one agent or workflow invocation."""

    trajectory_id: str
    steps: tuple[Step, ...]
    execution: ExecutionResult | None = None
    recording_id: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "recording_id": self.recording_id,
            "source": self.source,
            "execution": self.execution.to_dict() if self.execution else None,
            "metadata": dict(self.metadata),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Trajectory:
        return cls(
            trajectory_id=value["trajectory_id"],
            recording_id=str(value.get("recording_id") or ""),
            execution=(
                ExecutionResult.from_dict(value["execution"])
                if isinstance(value.get("execution"), dict)
                else None
            ),
            source=value.get("source", ""),
            metadata=dict(value.get("metadata", {})),
            steps=tuple(Step.from_dict(step) for step in value.get("steps", ())),
        )
