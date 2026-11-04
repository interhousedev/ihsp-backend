"""Fixtures of the real-model evals: off unless asked for, capped, one report."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from app.settings import Settings
from app.shared.contracts.ai import LlmGateway
from tests.ai.evals.run import EvalRun, RecordingGateway, real_gateway
from tests.fakes.clock import FixedClock
from tests.notebooks.conftest import module_deps, uow_factory

import pytest

__all__ = ["module_deps", "uow_factory"]

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every eval, and skip them all unless IHSP_AI_EVAL=1."""
    skip = None
    if os.environ.get("IHSP_AI_EVAL") != "1":
        skip = pytest.mark.skip(reason="real-model evals need IHSP_AI_EVAL=1")
    for item in items:
        if _HERE in Path(str(item.path)).parents:
            item.add_marker(pytest.mark.real_model)
            if skip is not None:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def settings(settings: Settings) -> Settings:
    """The test settings with OpenUI on, as the assistants run it."""
    return settings.model_copy(
        update={"ai": settings.ai.model_copy(update={"openui_enabled": True})}
    )


@pytest.fixture
def clock() -> FixedClock:
    """A clock at the real time, so Redis keeps the notebook budget windows."""
    return FixedClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture(scope="session")
def eval_run() -> EvalRun:
    """The cap and the report of this process."""
    return EvalRun.from_env()


@pytest.fixture(scope="session")
async def real_llm(settings: Settings, eval_run: EvalRun) -> AsyncIterator[LlmGateway]:
    """The production gateway; refuses to start without real mode and a key."""
    if settings.openrouter.mode != "real":
        pytest.fail("evals need IHSP_OPENROUTER__MODE=real")
    key = settings.openrouter.api_key
    if key is None or not key.get_secret_value():
        pytest.fail("evals need IHSP_OPENROUTER__API_KEY in the environment")
    gateway = real_gateway(settings, eval_run)
    yield cast(LlmGateway, RecordingGateway(gateway, eval_run))
    await gateway.aclose()
