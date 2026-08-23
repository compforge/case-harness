"""Detect exact repeated tool calls, a common agent-loop churn finding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from trajectory_harness.evaluate import (
    EvaluationResult,
    EvaluatorSpec,
    Finding,
)
from trajectory_harness.model import Step, Trajectory


@dataclass(frozen=True, slots=True)
class RepeatedToolCallEvaluator:
    spec: EvaluatorSpec = EvaluatorSpec(
        evaluator_id="repeated_tool_call",
        title="Repeated tool calls",
        description="Detect exact repeats of an earlier tool name and arguments.",
        kind="common",
        owner="trajectory_harness",
    )

    def evaluate(
        self, trajectory: Trajectory, reference: Trajectory | None = None
    ) -> EvaluationResult:
        del reference
        calls = _tool_calls(trajectory.steps)
        if not calls:
            return EvaluationResult(
                evaluator_id=self.spec.evaluator_id,
                status="not_applicable",
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

        if duplicate_steps:
            summary = (
                f"{len(duplicate_steps)} of {len(calls)} tool calls repeat an earlier "
                "tool name and arguments."
            )
            return EvaluationResult(
                evaluator_id=self.spec.evaluator_id,
                status="evaluated",
                verdict="warning",
                explanation=f"{summary} Inspect whether batching or reuse would help.",
                step_ids=tuple(duplicate_steps),
                findings=(
                    Finding(
                        code="repeated_tool_call",
                        severity="warning",
                        summary=summary,
                        step_ids=tuple(duplicate_steps),
                        hypotheses=(
                            "The tool may be missing a batch operation.",
                            "The tool description may not encourage batching or result reuse.",
                            "The agent loop may lack an effective repeat-call stopping strategy.",
                        ),
                    ),
                ),
            )
        return EvaluationResult(
            evaluator_id=self.spec.evaluator_id,
            status="evaluated",
            score=1.0,
            verdict="pass",
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
