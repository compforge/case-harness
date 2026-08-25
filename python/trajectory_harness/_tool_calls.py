"""Internal canonical view of tool calls embedded in trajectory steps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from trajectory_harness.model import Step


@dataclass(frozen=True, slots=True)
class ToolCall:
    step: Step
    name: str
    arguments: Any

    @property
    def signature(self) -> tuple[str, str]:
        return (
            self.name,
            json.dumps(self.arguments, sort_keys=True, ensure_ascii=False),
        )


def tool_calls(steps: tuple[Step, ...]) -> tuple[ToolCall, ...]:
    """Return executed calls when available, otherwise model-requested calls."""

    executed = tuple(step for step in steps if step.operation == "execute_tool")
    if executed:
        return tuple(
            call
            for step in executed
            for call in _calls_in_step(step, prefer_input=True)
        )
    return tuple(
        call for step in steps for call in _calls_in_step(step, prefer_input=False)
    )


def tool_names(step: Step) -> tuple[str, ...]:
    return tuple(call.name for call in _calls_in_step(step, prefer_input=True))


def _calls_in_step(step: Step, *, prefer_input: bool) -> tuple[ToolCall, ...]:
    messages = step.input_messages if prefer_input else step.output_messages
    calls = []
    for message in messages:
        for part in message.get("parts", []):
            if part.get("type") != "tool_call":
                continue
            calls.append(
                ToolCall(
                    step=step,
                    name=str(part.get("name") or ""),
                    arguments=part.get("arguments"),
                )
            )
    return tuple(calls)
