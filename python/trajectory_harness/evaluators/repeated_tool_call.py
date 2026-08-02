"""Detect exact repeated tool calls, a common agent-loop churn signal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from trajectory_harness.evaluate import Evaluation
from trajectory_harness.model import Step, Trajectory


@dataclass(frozen=True, slots=True)
class RepeatedToolCallEvaluator:
    name: str = "repeated_tool_call"
    weight: float = 1.0

    def evaluate(
        self, trajectory: Trajectory, reference: Trajectory | None = None
    ) -> Evaluation:
        del reference
        calls = _tool_calls(trajectory.steps)
        if not calls:
            return Evaluation(
                name=self.name,
                score=None,
                label="not_evaluated",
                explanation="Trajectory contains no tool calls.",
            )

        seen = set()
        duplicate_steps = []
        for step_id, tool, arguments in calls:
            signature = (
                tool,
                json.dumps(arguments, sort_keys=True, ensure_ascii=False),
            )
            if signature in seen:
                duplicate_steps.append(step_id)
            else:
                seen.add(signature)

        score = round(1 - len(duplicate_steps) / len(calls), 3)
        if duplicate_steps:
            return Evaluation(
                name=self.name,
                score=score,
                label="fail",
                explanation=(
                    f"{len(duplicate_steps)} of {len(calls)} tool calls repeat an earlier "
                    "tool name and arguments."
                ),
                step_ids=tuple(duplicate_steps),
            )
        return Evaluation(
            name=self.name,
            score=1.0,
            label="pass",
            explanation=f"All {len(calls)} tool calls are distinct.",
        )


def _tool_calls(steps: tuple[Step, ...]) -> list[tuple[str, str, Any]]:
    executed = [step for step in steps if step.operation == "execute_tool"]
    if executed:
        return [
            call
            for step in executed
            for call in _calls_in_step(step, prefer_input=True)
        ]
    return [call for step in steps for call in _calls_in_step(step, prefer_input=False)]


def _calls_in_step(step: Step, *, prefer_input: bool) -> list[tuple[str, str, Any]]:
    messages = step.input_messages if prefer_input else step.output_messages
    calls = []
    for message in messages:
        for part in message.get("parts", []):
            if part.get("type") != "tool_call":
                continue
            calls.append(
                (
                    step.step_id,
                    str(part.get("name") or ""),
                    part.get("arguments"),
                )
            )
    return calls
