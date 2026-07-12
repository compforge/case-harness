"""correctness — LLM-as-judge metric.

Service points its MetricRegistry at the ``metrics`` package; the registry
picks up each module and treats ``NAME`` + ``score(sample)`` as the metric
contract. Async metrics (LLM-judge) work transparently — score_dataset awaits.
"""

from e2e_harness import BaseLLMJudge, EvalSample, LLMClient, MetricResult

NAME = "correctness"


class CorrectnessJudge(BaseLLMJudge):
    NAME = "correctness"
    SYSTEM_PROMPT = (
        "You are an evaluator. Compare the response to the expected answer. "
        "Output JSON: {\"score\": 0~1, \"judgement\": \"<one-line reason>\"}."
    )

    def build_prompt(self, sample: EvalSample) -> str:
        return (
            f"Question: {sample.user_input}\n"
            f"Response: {sample.response}\n"
            f"Expected: {sample.reference}\n"
        )

    def applies_to(self, sample: EvalSample) -> bool:
        # Only answer-style cases — refuse cases use a different metric.
        return sample.expected_behavior == "answer" and bool(sample.reference)


_judge = CorrectnessJudge(LLMClient.from_env())


async def score(sample: EvalSample) -> MetricResult:
    return await _judge.score(sample)
