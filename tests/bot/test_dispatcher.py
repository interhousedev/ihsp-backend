"""Dispatcher wiring, storage, commands and the webhook server."""

from app.interfaces.bot.bot import (
    COMMAND_KEYS,
    FSM_TTL_SECONDS,
    build_commands,
    build_dispatcher,
    build_storage,
    set_commands,
)
from app.interfaces.bot.routers import build_routers
from app.interfaces.bot.webhook import build_webhook_app, webhook_path
from app.settings import Settings
from tests.bot.support.fakes import World
from tests.bot.support.recording_bot import make_bot, message_update, session_of

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.methods import SetMyCommands
from aiohttp.test_utils import TestClient, TestServer
from pydantic import SecretStr


def test_two_dispatchers_can_be_built_in_one_process(world: World) -> None:
    """Routers are built per dispatcher (a Router has one parent only)."""
    first = build_dispatcher(world.container, MemoryStorage())
    second = build_dispatcher(world.container, MemoryStorage())

    assert first is not second
    assert len(build_routers()) == len(build_routers())


def test_the_dispatcher_listens_to_block_updates(dp: Dispatcher) -> None:
    """BOT-22: my_chat_member must be among the updates the bot asks for."""
    used = dp.resolve_used_update_types()

    assert {"message", "callback_query", "my_chat_member"} <= set(used)


def test_fsm_storage_is_redis_with_a_one_hour_ttl() -> None:
    """BOT-4: FSM state lives in Redis for one hour, under its own prefix."""
    settings = Settings(env="test", telegram={"mode": "polling"})

    storage = build_storage(settings)

    assert isinstance(storage, RedisStorage)
    assert FSM_TTL_SECONDS == 3600
    assert storage.state_ttl == 3600
    assert storage.data_ttl == 3600
    key = StorageKey(bot_id=7, chat_id=1, user_id=2)
    assert storage.key_builder.build(key, "state").startswith("ihsp:fsm:7:")


def test_fake_mode_uses_memory_storage() -> None:
    """Fake mode needs no Redis."""
    assert isinstance(build_storage(Settings(env="test")), MemoryStorage)


def test_commands_follow_the_menu(world: World) -> None:
    """BOT-9: the command list has the slash commands of the menu."""
    commands = build_commands(world.i18n, "en")

    assert [c.command for c in commands] == [
        "start",
        "menu",
        "today",
        "marks",
        "homework",
        "mail",
        "settings",
        "help",
    ]
    assert set(COMMAND_KEYS.values()) == {c.description for c in commands}


async def test_commands_are_published_per_language(world: World) -> None:
    """A default list and one per supported language."""
    bot = make_bot()

    await set_commands(bot, world.i18n)

    calls = session_of(bot).calls(SetMyCommands)
    assert [c.language_code for c in calls] == [None, "uz", "ru", "en"]


async def test_webhook_checks_the_secret_and_feeds_the_dispatcher(
    world: World,
) -> None:
    """Webhook mode: wrong secret header gives 401, the right one runs the handlers."""
    settings = Settings(
        env="test",
        telegram={
            "mode": "webhook",
            "webhook_url": "https://bot.example.test/",
            "webhook_secret": SecretStr("s3cret"),
        },
    )
    world.container.settings = settings
    bot = make_bot()
    dispatcher = build_dispatcher(world.container, MemoryStorage())
    app = build_webhook_app(bot, dispatcher, world.container, settings)
    update = message_update(bot, "/start", user_id=7777).model_dump_json(
        exclude_none=True
    )

    async with TestClient(TestServer(app)) as client:
        path = webhook_path("s3cret")
        wrong = await client.post(
            path,
            data=update,
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": "nope",
            },
        )
        right = await client.post(
            path,
            data=update,
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": "s3cret",
            },
        )

    assert wrong.status == 401
    assert right.status == 200


def test_webhook_mode_needs_a_url_and_a_secret(world: World) -> None:
    """A webhook without a secret would accept anyone's updates."""
    settings = Settings(env="test", telegram={"mode": "webhook"})
    bot = make_bot()
    dispatcher = build_dispatcher(world.container, MemoryStorage())

    with pytest.raises(ValueError, match="WEBHOOK_SECRET"):
        build_webhook_app(bot, dispatcher, world.container, settings)
