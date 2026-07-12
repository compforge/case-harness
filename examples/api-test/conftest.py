"""pytest fixtures — wire env / runner / judge from config.yaml."""

from e2e_harness.conftest_helpers import env_fixture, judge_fixture, runner_fixture

env = env_fixture("config.yaml")
runner = runner_fixture()
judge = judge_fixture()
