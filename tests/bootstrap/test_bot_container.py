"""The bot builds its container without the OpenRouter and Exa keys."""

from app.bootstrap.common import PLANS, BuildOverrides, build_container
from app.settings import Settings
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis


@pytest.fixture
def keyless(settings: Settings) -> Settings:
    """Real OpenRouter and Exa without their keys, as the bot runs in production."""
    openrouter = settings.openrouter.model_copy(
        update={"mode": "real", "api_key": None}
    )
    exa = settings.exa.model_copy(update={"mode": "real", "api_key": None})
    return settings.model_copy(update={"openrouter": openrouter, "exa": exa})


async def test_the_bot_container_builds_without_the_ai_keys(
    keyless: Settings, redis: FakeRedis
) -> None:
    assert PLANS["bot"].ai_keys is False

    container = await build_container(
        keyless,
        process="bot",
        kicker=FakeTaskKicker(),
        overrides=BuildOverrides(redis=redis),
    )
    try:
        assert container.ai is not None
        assert container.notify is not None
    finally:
        await container.close()
