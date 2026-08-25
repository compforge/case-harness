"""Measure input-context growth and observed compaction boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from trajectory_harness._steps import is_compact_step
from trajectory_harness.measure import MeasurementResult, MeasurementSpec, MeasurerSpec
from trajectory_harness.measurers._tokens import (
    INPUT_TOKEN_ATTRIBUTES,
    MODEL_OPERATIONS,
    token_count,
)
from trajectory_harness.model import Step, Trajectory

_DISTRIBUTION_AGGREGATIONS = ("sum", "mean", "p50", "p95")


@dataclass(frozen=True, slots=True)
class ContextUsageMeasurer:
    """Measure reported model-input growth around one trajectory's compact events."""

    spec: MeasurerSpec = MeasurerSpec(
        measurer_id="context_usage",
        title="Context usage",
        description=(
            "Measure model-input coverage and growth plus observed context compaction."
        ),
        owner="trajectory_harness",
        measurements=(
            MeasurementSpec(
                "model_call_count",
                "count",
                "Observed model calls.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "input_reported_call_count",
                "count",
                "Model calls reporting input tokens.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "input_coverage_ratio",
                "ratio",
                "Model calls reporting input tokens divided by model calls.",
                "higher_is_better",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "first_input_tokens",
                "token",
                "Reported input tokens for the first covered model call.",
                "neutral",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "last_input_tokens",
                "token",
                "Reported input tokens for the last covered model call.",
                "neutral",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "peak_input_tokens",
                "token",
                "Largest reported input token count.",
                "neutral",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "input_token_delta",
                "token",
                "Last minus first reported input tokens.",
                "neutral",
                ("mean", "p50", "p95"),
            ),
            MeasurementSpec(
                "compact_count",
                "count",
                "Observed context-compaction steps.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "post_compact_observed_count",
                "count",
                "Compact steps with covered model calls immediately before and after.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
            MeasurementSpec(
                "post_compact_input_delta_tokens",
                "token",
                "Total after-minus-before input-token change across compact boundaries.",
                "neutral",
                _DISTRIBUTION_AGGREGATIONS,
            ),
        ),
    )

    def measure(self, trajectory: Trajectory) -> MeasurementResult:
        ordered = tuple(
            step
            for _, step in sorted(
                enumerate(trajectory.steps),
                key=lambda item: (item[1].start_ms, item[0]),
            )
        )
        model_calls = tuple(
            step for step in ordered if step.operation in MODEL_OPERATIONS
        )
        compacts = tuple(step for step in ordered if is_compact_step(step))
        if not model_calls and not compacts:
            return MeasurementResult(
                measurer_id=self.spec.measurer_id,
                status="not_applicable",
                explanation="Trajectory contains no model calls or compact steps.",
            )

        covered = tuple(
            (step, count)
            for step in model_calls
            if (count := token_count(step, INPUT_TOKEN_ATTRIBUTES)) is not None
        )
        measurements: dict[str, float | int | bool] = {
            "model_call_count": len(model_calls),
            "input_reported_call_count": len(covered),
            "compact_count": len(compacts),
        }
        if model_calls:
            measurements["input_coverage_ratio"] = round(
                len(covered) / len(model_calls), 6
            )
        if covered:
            counts = [count for _, count in covered]
            measurements.update(
                {
                    "first_input_tokens": counts[0],
                    "last_input_tokens": counts[-1],
                    "peak_input_tokens": max(counts),
                    "input_token_delta": counts[-1] - counts[0],
                }
            )

        compact_observations = _compact_reductions(ordered, covered, compacts)
        measurements["post_compact_observed_count"] = len(compact_observations)
        if compact_observations:
            measurements["post_compact_input_delta_tokens"] = sum(compact_observations)

        return MeasurementResult(
            measurer_id=self.spec.measurer_id,
            status="measured",
            measurements=measurements,
            explanation=(
                f"Observed {len(model_calls)} model calls and {len(compacts)} "
                "compact steps."
            ),
            step_ids=tuple(
                dict.fromkeys(
                    [step.step_id for step, _ in covered]
                    + [step.step_id for step in compacts]
                )
            ),
        )


def _compact_reductions(
    ordered: tuple[Step, ...],
    covered: tuple[tuple[Step, int], ...],
    compacts: tuple[Step, ...],
) -> list[int]:
    positions = {step.step_id: index for index, step in enumerate(ordered)}
    observed = []
    for compact in compacts:
        compact_index = positions[compact.step_id]
        before = [
            (positions[step.step_id], count)
            for step, count in covered
            if positions[step.step_id] < compact_index
        ]
        after = [
            (positions[step.step_id], count)
            for step, count in covered
            if positions[step.step_id] > compact_index
        ]
        if before and after:
            observed.append(after[0][1] - before[-1][1])
    return observed
