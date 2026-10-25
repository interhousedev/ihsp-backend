"""Process entry of the Telegram bot (``python -m app bot``)."""

import asyncio
from typing import Any

from app.interfaces.bot.bot import (
    build_bot,
    build_dispatcher,
    build_storage,
    set_commands,
)
from app.interfaces.bot.webhook import run_webhook
from app.settings import Settings

import structlog
from aiogram import Bot, Dispatcher

log = structlog.get_logger(__name__)


async def _poll(bot: Bot, dispatcher: Dispatcher, container: Any) -> None:
    """Long polling (development); polling and webhook exclude each other."""
    await bot.delete_webhook()
    await dispatcher.start_polling(
        bot,
        container=container,
        allowed_updates=dispatcher.resolve_used_update_types(),
    )


async def run_bot(container: Any) -> None:
    """Run the bot in the mode of ``TELEGRAM__MODE`` until cancelled.

    ``fake`` mode never touches the network: tests feed updates to the dispatcher.
    """
    settings: Settings = container.settings
    mode = settings.telegram.mode
    bot = build_bot(settings)
    dispatcher = build_dispatcher(container, build_storage(settings))
    try:
        if mode == "fake":
            log.info("bot.fake_mode")
            await asyncio.Event().wait()
            return
        await set_commands(bot, container.i18n)
        if mode == "webhook":
            await run_webhook(bot, dispatcher, container, settings)
        else:
            await _poll(bot, dispatcher, container)
    finally:
        await bot.session.close()
