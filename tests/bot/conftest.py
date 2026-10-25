"""Fixtures of the bot tests: a recording bot, a dispatcher and fake contracts."""

from collections.abc import AsyncIterator

from app.interfaces.bot.bot import build_dispatcher
from tests.bot.support.fakes import World, build_world
from tests.bot.support.harness import Harness
from tests.bot.support.recording_bot import make_bot

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage


@pytest.fixture
def world() -> World:
    """Fake contracts with a linked student (1001) and teacher (2002)."""
    return build_world()


@pytest.fixture
def bot() -> Bot:
    """A bot that records requests."""
    return make_bot()


@pytest_asyncio.fixture
async def dp(world: World) -> AsyncIterator[Dispatcher]:
    """A fresh dispatcher per test (routers are built per dispatcher)."""
    dispatcher = build_dispatcher(world.container, MemoryStorage())
    yield dispatcher
    await dispatcher.storage.close()


@pytest.fixture
def harness(bot: Bot, dp: Dispatcher, world: World) -> Harness:
    """The test harness."""
    return Harness(bot, dp, world)
