"""Verify tool execution success across a trajectory."""

from __future__ import annotations

from dataclasses import dataclass

from trajectory_harness.model import Trajectory
from trajectory_harness.measure import Measurements
from trajectory_harness.verify import VerificationResult, VerifierSpec


@dataclass(frozen=True, slots=True)
class ToolSuccessVerifier:
    spec: VerifierSpec = VerifierSpec(
        verifier_id="tool_success",
        title="Tool success",
        description="Check whether tool executions in the trajectory succeeded.",
        category="effect",
        kind="common",
        owner="trajectory_harness",
    )

    def verify(
        self,
        trajectory: Trajectory,
        *,
        measurements: Measurements = (),
        reference: Trajectory | None = None,
    ) -> VerificationResult:
        del measurements, reference
        calls = [step for step in trajectory.steps if step.operation == "execute_tool"]
        if not calls:
            return VerificationResult(
                verifier_id=self.spec.verifier_id,
                status="not_applicable",
                explanation="Trajectory contains no executed tool calls.",
            )

        failed = [step for step in calls if step.failure or step.status == "error"]
        success_rate = round((len(calls) - len(failed)) / len(calls), 3)
        return VerificationResult(
            verifier_id=self.spec.verifier_id,
            status="verified",
            verdict="pass" if not failed else "fail",
            score=success_rate,
            explanation=(
                f"{len(calls) - len(failed)} of {len(calls)} tool calls succeeded."
            ),
            step_ids=tuple(step.step_id for step in failed),
        )
