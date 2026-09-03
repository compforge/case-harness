"""Detect exact pre-compact tool calls fetched again after compaction."""

from __future__ import annotations

from dataclasses import dataclass

from trajectory_harness._steps import is_compact_step
from trajectory_harness._tool_calls import tool_calls
from trajectory_harness.detect import DetectionResult, DetectorSpec, Finding
from trajectory_harness.measure import Measurements
from trajectory_harness.model import Trajectory


@dataclass(frozen=True, slots=True)
class PostCompactRefetchDetector:
    spec: DetectorSpec = DetectorSpec(
        detector_id="post_compact_refetch",
        title="Post-compact refetch",
        description="Detect exact tool calls repeated across a context-compaction boundary.",
        category="cost",
        kind="common",
        owner="trajectory_harness",
    )

    def detect(
        self, trajectory: Trajectory, *, measurements: Measurements = ()
    ) -> DetectionResult:
        del measurements
        positions = {
            step.step_id: position
            for position, (_, step) in enumerate(
                sorted(
                    enumerate(trajectory.steps),
                    key=lambda item: (item[1].start_ms, item[0]),
                )
            )
        }
        compact_positions = tuple(
            positions[step.step_id]
            for step in trajectory.steps
            if is_compact_step(step)
        )
        if not compact_positions:
            return DetectionResult(
                detector_id=self.spec.detector_id,
                status="not_applicable",
                explanation="Trajectory contains no context-compaction step.",
            )
        calls = tool_calls(trajectory.steps)
        if not calls:
            return DetectionResult(
                detector_id=self.spec.detector_id,
                status="not_applicable",
                explanation="Trajectory contains no tool calls around compaction.",
            )

        earlier: dict[tuple[str, str], list[tuple[int, str]]] = {}
        pairs = []
        for call in sorted(
            calls,
            key=lambda item: positions.get(item.step.step_id, 0),
        ):
            position = positions.get(call.step.step_id, 0)
            prior = earlier.get(call.signature, [])
            matching = next(
                (
                    step_id
                    for prior_position, step_id in reversed(prior)
                    if any(
                        prior_position < compact_position < position
                        for compact_position in compact_positions
                    )
                ),
                None,
            )
            if matching:
                pairs.append((matching, call.step.step_id))
            earlier.setdefault(call.signature, []).append((position, call.step.step_id))

        if not pairs:
            return DetectionResult(
                detector_id=self.spec.detector_id,
                status="analyzed",
                explanation="No exact tool call was repeated across compaction.",
            )

        step_ids = tuple(dict.fromkeys(step_id for pair in pairs for step_id in pair))
        summary = f"{len(pairs)} exact tool-call pairs cross a compact boundary."
        return DetectionResult(
            detector_id=self.spec.detector_id,
            status="analyzed",
            explanation=summary,
            findings=(
                Finding(
                    code="post_compact_refetch",
                    severity="warning",
                    summary=summary,
                    step_ids=step_ids,
                    hypotheses=(
                        "The compact summary may omit stable evidence identifiers.",
                        "The agent may not retain or trust pre-compact tool results.",
                        "The external resource may require a freshness refresh.",
                    ),
                ),
            ),
        )
