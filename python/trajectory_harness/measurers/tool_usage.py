"""Measure executed tool usage without inferring whether calls were necessary."""

from __future__ import annotations

import json
from dataclasses import dataclass

from trajectory_harness.measure import MeasurementResult, MeasurementSpec, MeasurerSpec
from trajectory_harness.model import Step, Trajectory

_DISTRIBUTION_AGGREGATIONS = ("sum", "mean", "p50", "p95")


@dataclass(frozen=True, slots=True)
class ToolUsageMeasurer:
    """Measure executed tool calls, failures, latency, output size, and concurrency."""

    spec: MeasurerSpec = MeasurerSpec(
        measurer_id="tool_usage",
        title="Tool usage",
        description=(
            "Measure executed tool calls, normalized failures, duration, result "
            "coverage, result bytes, and observed concurrency."
        ),
        owner="trajectory_harness",
        measurements=(
            MeasurementSpec(
                "tool_call_count",
                "count",
                "Executed tool calls.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "failed_tool_call_count",
                "count",
                "Executed tool calls carrying a normalized failure.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "tool_failure_ratio",
                "ratio",
                "Failed executed tool calls divided by all executed tool calls.",
                "lower_is_better",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "tool_duration_ms",
                "ms",
                "Total duration of executed tool calls.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "result_reported_call_count",
                "count",
                "Executed tool calls carrying output messages.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "result_coverage_ratio",
                "ratio",
                "Tool calls carrying output messages divided by executed calls.",
                "higher_is_better",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "result_bytes",
                "byte",
                "UTF-8 JSON size of reported tool output messages.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "max_concurrent_tool_calls",
                "count",
                "Largest number of overlapping executed tool-call steps.",
                "neutral",
                ("mean", "p50", "p95"),
            ),
        ),
    )

    def measure(self, trajectory: Trajectory) -> MeasurementResult:
        calls = tuple(
            step for step in trajectory.steps if step.operation == "execute_tool"
        )
        if not calls:
            return MeasurementResult(
                measurer_id=self.spec.measurer_id,
                status="not_applicable",
                explanation="Trajectory contains no executed tool-call steps.",
            )

        failed = sum(call.failure is not None for call in calls)
        reported = tuple(call for call in calls if call.output_messages)
        measurements: dict[str, float | int | bool] = {
            "tool_call_count": len(calls),
            "failed_tool_call_count": failed,
            "tool_failure_ratio": round(failed / len(calls), 6),
            "tool_duration_ms": round(sum(call.duration_ms for call in calls), 6),
            "result_reported_call_count": len(reported),
            "result_coverage_ratio": round(len(reported) / len(calls), 6),
            "result_bytes": sum(_output_bytes(call) for call in reported),
            "max_concurrent_tool_calls": _max_concurrency(calls),
        }
        return MeasurementResult(
            measurer_id=self.spec.measurer_id,
            status="measured",
            measurements=measurements,
            explanation=(
                f"Observed {len(calls)} executed tool calls; "
                f"{len(reported)} reported output messages."
            ),
            step_ids=tuple(call.step_id for call in calls),
        )


def _output_bytes(step: Step) -> int:
    payload = json.dumps(
        list(step.output_messages),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


def _max_concurrency(calls: tuple[Step, ...]) -> int:
    intervals = [
        (call.start_ms, call.start_ms + call.duration_ms)
        for call in calls
        if call.duration_ms > 0
    ]
    if not intervals:
        return 1
    events = sorted(
        (event for start, end in intervals for event in ((start, 1), (end, -1))),
        key=lambda item: (item[0], item[1]),
    )
    current = 0
    peak = 0
    for _, change in events:
        current += change
        peak = max(peak, current)
    return max(1, peak)
