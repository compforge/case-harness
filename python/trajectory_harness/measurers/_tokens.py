"""Shared token-usage attribute parsing for trajectory measurers."""

from __future__ import annotations

import math
from typing import Any

from trajectory_harness.model import Step

MODEL_OPERATIONS = {
    "inference",
    "chat",
    "completion",
    "generate_content",
    "text_completion",
    "embeddings",
}
INPUT_TOKEN_ATTRIBUTES = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.prompt_tokens",
    "llm.token_count.prompt",
    "input_tokens",
    "prompt_tokens",
)
OUTPUT_TOKEN_ATTRIBUTES = (
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.completion_tokens",
    "llm.token_count.completion",
    "output_tokens",
    "completion_tokens",
)
CACHED_INPUT_TOKEN_ATTRIBUTES = (
    "gen_ai.usage.cached_input_tokens",
    "gen_ai.usage.cache_read.input_tokens",
    "gen_ai.usage.cache_read_tokens",
    "cached_input_tokens",
    "cache_read_tokens",
    "cached_tokens",
)


def token_count(step: Step, names: tuple[str, ...]) -> int | None:
    for name in names:
        value = _non_negative_int(step.attributes.get(name))
        if value is not None:
            return value
    return None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)
