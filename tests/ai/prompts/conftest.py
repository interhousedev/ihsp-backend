"""Fixtures of the prompt tests: settings with OpenUI on, as the assistants run it."""

from app.settings import Settings

import pytest


@pytest.fixture(scope="session")
def settings(settings: Settings) -> Settings:
    """The test settings with OpenUI on, whatever the environment file says."""
    return settings.model_copy(
        update={"ai": settings.ai.model_copy(update={"openui_enabled": True})}
    )
