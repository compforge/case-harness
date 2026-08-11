import pytest

from e2e_harness import Env, JSONRunner, load_env


@pytest.fixture(scope="session")
def env() -> Env:
    return load_env("config.yaml")


@pytest.fixture(scope="session")
def runner(env: Env):
    with JSONRunner(env) as value:
        yield value
