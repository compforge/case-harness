"""Internal predicates over canonical trajectory steps."""

from trajectory_harness.model import Step


def is_compact_step(step: Step) -> bool:
    operation = step.operation.lower().replace("_", ".")
    name = step.name.lower().replace("_", ".")
    return operation in {"compact", "context.compact"} or name in {
        "compact",
        "context.compact",
    }
