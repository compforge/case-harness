"""Common low-cardinality failure taxonomy.

Loaders classify source-specific errors; this module only provides shared
vocabulary and constructors for failure families that recur across agents.
"""

from __future__ import annotations

from typing import Literal

from trajectory_harness.model import Failure

LLMFailurePhase = Literal["routing", "request", "response_parse"]
LLMErrorType = Literal[
    "timeout",
    "rate_limit",
    "client_error",
    "server_error",
    "network_error",
    "invalid_response",
    "unknown",
]


def llm_failure(
    phase: LLMFailurePhase,
    error_type: LLMErrorType,
    *,
    code: str = "",
    message: str = "",
) -> Failure:
    """Build a normalized LLM failure without prescribing source parsing."""

    return Failure(
        kind="llm",
        phase=phase,
        error_type=error_type,
        code=code,
        message=message,
    )
