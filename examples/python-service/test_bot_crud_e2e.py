import uuid
from dataclasses import dataclass

from e2e_harness import (
    Budgets,
    CaseRef,
    CaseRun,
    Fail,
    JSONRunner,
    Request,
    run_lifecycle,
)


@dataclass
class State:
    name: str = ""
    bot_id: str = ""


def test_bot_crud(runner: JSONRunner):
    state = State()

    def prepare(_, value: State):
        value.name = f"e2e-{uuid.uuid4().hex[:8]}"

    def execute(_, value: State):
        outcome = runner.trigger(
            Request(method="POST", path="/api/v1/bots", body={"name": value.name})
        )
        if outcome.status_code != 200 or not outcome.field_str("id"):
            raise RuntimeError(f"create failed: {outcome.status_code}")
        value.bot_id = outcome.field_str("id")

    def judge(_, value: State):
        outcome = runner.trigger(Request(method="GET", path=f"/api/v1/bots/{value.bot_id}"))
        if outcome.status_code != 200 or outcome.field_str("name") != value.name:
            raise Fail("created bot is not readable with the same name")

    def cleanup(_, value: State):
        if value.bot_id:
            runner.trigger(Request(method="DELETE", path=f"/api/v1/bots/{value.bot_id}"))

    result = run_lifecycle(
        CaseRef("control-bot", "create_and_get"),
        state,
        CaseRun(
            prepare=prepare,
            execute=execute,
            judge=judge,
            cleanup=cleanup,
            budgets=Budgets(30, 30, 60, 30),
        ),
    )
    assert result.status == "pass", result.reason
