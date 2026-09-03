import pytest

from e2e_harness import E2EConfig, JSONRunner, load_config


@pytest.fixture(scope="session")
def config() -> E2EConfig:
    return load_config("config.yaml")


@pytest.fixture(scope="session")
def runner(config: E2EConfig):
    with JSONRunner(config) as value:
        yield value
