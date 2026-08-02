"""Agent trajectory normalization and evaluation.

External recordings are first projected into the small ``Trajectory`` IR.  Evaluators
then consume that IR without knowing whether it came from OTel, a framework session, or
another trace format.
"""

from trajectory_harness.evaluate import Evaluation as Evaluation
from trajectory_harness.evaluate import EvaluationReport as EvaluationReport
from trajectory_harness.evaluate import Evaluator as Evaluator
from trajectory_harness.evaluate import evaluate as evaluate
from trajectory_harness.evaluators.repeated_tool_call import (
    RepeatedToolCallEvaluator as RepeatedToolCallEvaluator,
)
from trajectory_harness.loaders.base import TrajectoryLoader as TrajectoryLoader
from trajectory_harness.loaders.otel_json import OTelJsonLoader as OTelJsonLoader
from trajectory_harness.model import Step as Step
from trajectory_harness.model import Trajectory as Trajectory
