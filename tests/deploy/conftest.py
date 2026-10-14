"""Fixtures of the deployment tests: resolved compose models of both stacks."""

from pathlib import Path
from typing import Any

from tests.deploy.helpers import (
    LOCAL_COMPOSE,
    PROD_COMPOSE,
    PROD_ENV_SAMPLE,
    compose_json,
    docker_compose_available,
)

import pytest


def _require_docker() -> None:
    """Skip a test that resolves a compose model when `docker compose` is missing."""
    if not docker_compose_available():
        pytest.skip("docker compose is not available")


@pytest.fixture(scope="session")
def prod_model() -> dict[str, Any]:
    """The production stack resolved with materials/.env.prod.sample."""
    _require_docker()
    return compose_json(PROD_COMPOSE, PROD_ENV_SAMPLE)


@pytest.fixture(scope="session")
def local_model() -> dict[str, Any]:
    """The local full stack resolved with its defaults."""
    _require_docker()
    return compose_json(LOCAL_COMPOSE)


@pytest.fixture(scope="session")
def prod_model_after_init(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """The production stack once prod_init.sh vault has stored the AppRole ids."""
    _require_docker()
    env: Path = tmp_path_factory.mktemp("env") / ".env.prod"
    env.write_text(
        PROD_ENV_SAMPLE.read_text(encoding="utf-8")
        + "IHSP_VAULT__ROLE_ID=real-role\nIHSP_VAULT__SECRET_ID=real-secret\n"
        + "VAULT_BACKUP_ROLE_ID=backup-role\nVAULT_BACKUP_SECRET_ID=backup-secret\n",
        encoding="utf-8",
    )
    return compose_json(PROD_COMPOSE, env)
