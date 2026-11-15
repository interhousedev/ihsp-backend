"""Process entry of the Telegram bot (``python -m app bot``)."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.interfaces.bot.bot import (
    allowed_updates,
    bot_with_token,
    build_bot,
    build_dispatcher,
    build_storage,
    set_commands,
)
from app.interfaces.bot.webhook import run_webhook
from app.modules.admin.domain.errors import BotTokenInvalidError
from app.modules.admin.domain.telegram_bot import BotFeature, TelegramBot, token_bot_id
from app.modules.admin.infrastructure.bot_registry import BotRegistryCache
from app.settings import Settings

import structlog
from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonDefault

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RunningBot:
    """One bot of the process; ``entry`` is None for the bare env bot."""

    bot: Bot
    entry: TelegramBot | None


async def _poll(bots: Sequence[Bot], dispatcher: Dispatcher, container: Any) -> None:
    """Long polling (development); polling and webhook exclude each other."""
    for bot in bots:
        await bot.delete_webhook()
    await dispatcher.start_polling(
        *bots,
        container=container,
        allowed_updates=allowed_updates(dispatcher, container.settings),
    )


async def load_bots(container: Any, settings: Settings) -> list[RunningBot]:
    """The enabled registry bots; the env bot alone when the registry is unusable.

    The default bot comes first. On the first start the env token is imported as
    the default bot; it always runs with the env token, which Vault then follows.
    Without ``TELEGRAM__BOT_TOKEN`` the default bot runs on its Vault token and
    the process refuses to start when it cannot (no default bot, Vault down).
    """
    env_token = settings.telegram.bot_token.get_secret_value() or None
    admin = container.admin.bot_admin
    try:
        await admin.import_default_bot(env_token, settings.telegram.bot_username)
        entries = await admin.enabled_bots()
    except Exception:  # noqa: BLE001 - the env bot must keep working
        log.warning("bot_registry_unavailable", exc_info=True)
        entries = []
    running: list[RunningBot] = []
    for entry in sorted(entries, key=lambda bot: not bot.is_default):
        token = await admin.token_of(entry, env_token)
        if token is None:
            log.warning("bot_token_missing", bot_id=str(entry.id))
            continue
        running.append(RunningBot(bot_with_token(token), entry))
    if not running or running[0].entry is None or not running[0].entry.is_default:
        if env_token is None:
            raise RuntimeError(
                "no default bot: set TELEGRAM__BOT_TOKEN or run"
                " `python -m app import-default-bot` first"
            )
        running.insert(0, RunningBot(build_bot(settings), None))
    return running


async def configure(running: RunningBot, container: Any) -> None:
    """Commands and the menu button follow the feature switches."""
    entry, bot = running.entry, running.bot
    try:
        if entry is None or entry.has(BotFeature.COMMANDS):
            await set_commands(bot, container.i18n)
        else:
            await bot.delete_my_commands()
        if entry is not None and not entry.has(BotFeature.MINI_APP):
            await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception:  # noqa: BLE001 - one bot's setup must not stop the others
        log.warning("bot_configure_failed", exc_info=True)


def _env_bot_id(settings: Settings) -> int | None:
    """The env bot's Telegram id; it keeps working when the registry is stale."""
    token = settings.telegram.bot_token.get_secret_value()
    try:
        return token_bot_id(token) if token else None
    except BotTokenInvalidError:
        return None


async def run_bot(container: Any) -> None:
    """Run every enabled bot in the mode of ``TELEGRAM__MODE`` until cancelled.

    ``fake`` mode never touches the network: tests feed updates to the dispatcher.
    The set of bots is read at start; feature switches apply within 30 seconds.
    """
    settings: Settings = container.settings
    mode = settings.telegram.mode
    if mode == "fake":
        bot = build_bot(settings)
        build_dispatcher(container, build_storage(settings))
        try:
            log.info("bot.fake_mode")
            await asyncio.Event().wait()
        finally:
            await bot.session.close()
        return
    running = await load_bots(container, settings)
    default = running[0].entry
    registry = BotRegistryCache(
        container.sessionmaker,
        default_telegram_id=_env_bot_id(settings)
        or (default.telegram_id if default is not None else None),
    )
    dispatcher = build_dispatcher(container, build_storage(settings), registry)
    try:
        for item in running:
            await configure(item, container)
        bots = [item.bot for item in running]
        if mode == "webhook":
            extra = [
                (str(item.entry.id), item.bot)
                for item in running[1:]
                if item.entry is not None
            ]
            await run_webhook(bots[0], dispatcher, container, settings, extra)
        else:
            await _poll(bots, dispatcher, container)
    finally:
        for item in running:
            await item.bot.session.close()
