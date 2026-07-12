"""ChatRunner — sketches the minimal BaseEvalRunner subclass.

Triggers Chat action via AsyncSSERunner, extracts message_id from the first
``start`` event, returns RunHandle for downstream builder to look up the
finished message snapshot.
"""

from __future__ import annotations

from e2e_harness.eval import BaseEvalRunner, RunHandle
from e2e_harness.runner.async_sse_runner import AsyncSSERunner
from e2e_harness.runner.base import Request
from e2e_harness.runner.events import find_event_data


class ChatRunner(BaseEvalRunner):
    business_name = "chat"

    async def trigger_one(self, case, prep_case) -> RunHandle:
        env = self.ctx.pipeline.env  # service-side Pipeline exposes an Env or similar
        async with AsyncSSERunner(env) as runner:
            outcome = await runner.trigger(Request(
                method="POST", path="/",
                body={"ResourceID": prep_case.subject_id, "Query": case.question},
                query={"Action": "Chat", "Version": "2025-06-01"},
            ))

        start = find_event_data(outcome, op="start") or {}
        message = ((start.get("model") or {}).get("meta") or {}).get("message") or {}
        return RunHandle(
            case_id=case.id,
            business=self.business_name,
            subject_id=prep_case.subject_id,
            metadata={
                "message_id": message.get("id", ""),
                "conversation_id": message.get("conversation_id", ""),
                "trace_id": message.get("trace_id", ""),
            },
        )
