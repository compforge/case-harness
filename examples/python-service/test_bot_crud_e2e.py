"""Example: CRUD e2e test for control-server bot API."""

import uuid
from dataclasses import dataclass

from e2e_harness import BaseCase, BaseState, Env, JSONRunner, AssertJudge
from e2e_harness.runner.base import Request


@dataclass
class State(BaseState):
    bot_id: str | None = None
    bot_name: str | None = None


class TestCreateBot:
    """Create a bot, verify it exists, then delete it."""

    def test_create_and_get(self, env: Env, runner: JSONRunner, judge: AssertJudge):
        bot_name = f"{env.custom.get('bot_prefix', 'e2e-')}{uuid.uuid4().hex[:8]}"

        # Create
        outcome = runner.trigger(Request(
            method="POST",
            path="/api/v1/bots",
            body={"name": bot_name, "description": "e2e test bot"},
        ))
        judge.status(outcome, 200)
        judge.field_not_empty(outcome, "id")
        bot_id = outcome.field("id")

        try:
            # Get
            outcome = runner.trigger(Request(
                method="GET",
                path=f"/api/v1/bots/{bot_id}",
            ))
            judge.status(outcome, 200)
            judge.field_eq(outcome, "name", bot_name)
        finally:
            # Cleanup
            runner.trigger(Request(
                method="DELETE",
                path=f"/api/v1/bots/{bot_id}",
            ))

    def test_create_duplicate_name(self, env: Env, runner: JSONRunner, judge: AssertJudge):
        bot_name = f"{env.custom.get('bot_prefix', 'e2e-')}{uuid.uuid4().hex[:8]}"

        # Create first
        outcome = runner.trigger(Request(
            method="POST",
            path="/api/v1/bots",
            body={"name": bot_name, "description": "first"},
        ))
        judge.status(outcome, 200)
        bot_id = outcome.field("id")

        try:
            # Create duplicate
            outcome = runner.trigger(Request(
                method="POST",
                path="/api/v1/bots",
                body={"name": bot_name, "description": "duplicate"},
            ))
            judge.status(outcome, 409)
        finally:
            runner.trigger(Request(
                method="DELETE",
                path=f"/api/v1/bots/{bot_id}",
            ))


class TestCreateBotWithBaseCase:
    """Same test using BaseCase pattern for structured lifecycle."""

    def test_happy_path(self, env: Env, runner: JSONRunner):

        @dataclass
        class MyState(BaseState):
            bot_id: str | None = None

        class CreateBotCase(BaseCase[MyState]):
            state_cls = MyState

            def prepare(self):
                pass

            def run(self):
                name = f"{self.env.custom.get('bot_prefix', 'e2e-')}{uuid.uuid4().hex[:8]}"
                outcome = self.runner.trigger(Request(
                    method="POST",
                    path="/api/v1/bots",
                    body={"name": name, "description": "e2e lifecycle test"},
                ))
                self.judge.status(outcome, 200)
                self.judge.field_not_empty(outcome, "id")
                self.state.bot_id = outcome.field("id")

            def clean(self):
                if self.state.bot_id:
                    self.runner.trigger(Request(
                        method="DELETE",
                        path=f"/api/v1/bots/{self.state.bot_id}",
                    ))

        case = CreateBotCase(env, runner)
        case.execute()
