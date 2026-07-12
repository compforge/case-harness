"""Pytest fixtures for this service's e2e tests."""

import pytest

from e2e_harness import Env, JSONRunner, AssertJudge, load_env


@pytest.fixture(scope="session")
def env() -> Env:
    return load_env("config.yaml")


@pytest.fixture(scope="session")
def runner(env: Env) -> JSONRunner:
    r = JSONRunner(env)
    yield r
    r.close()


@pytest.fixture(scope="session")
def judge() -> AssertJudge:
    return AssertJudge()
