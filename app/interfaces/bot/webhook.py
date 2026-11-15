"""Webhook mode: an aiohttp server that feeds Telegram updates to the dispatcher."""

import asyncio
import hashlib
import hmac
from collections.abc import Sequence
from typing import Any

from app.interfaces.bot.bot import allowed_updates
from app.settings import Settings

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

WEBHOOK_HOST = "0.0.0.0"  # nosec B104 -- container behind nginx
WEBHOOK_PORT = 8002


def webhook_path(secret: str) -> str:
    """The default bot's route; the secret is part of it (unchanged on purpose)."""
    return f"/telegram/{secret}"


def _derive(secret: str, purpose: str, bot_key: str) -> str:
    message = f"{purpose}:{bot_key}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def bot_webhook_path(secret: str, bot_key: str) -> str:
    """Another registered bot's route: ``/telegram/b/{HMAC(secret, path:key)}``."""
    return f"/telegram/b/{_derive(secret, 'path', bot_key)}"


def bot_secret_token(secret: str, bot_key: str) -> str:
    """Another bot's ``X-Telegram-Bot-Api-Secret-Token``, distinct from its path.

    Each bot knows only its own derived values, so a secondary bot's token (which
    its owner sees in getWebhookInfo) never opens the default bot's route.
    """
    return _derive(secret, "header", bot_key)


def build_webhook_app(
    bot: Bot,
    dispatcher: Dispatcher,
    container: Any,
    settings: Settings,
    extra: Sequence[tuple[str, Bot]] = (),
) -> web.Application:
    """Build the aiohttp app; Telegram must send the secret token header.

    ``extra`` holds the other bots as (path key, bot); they share the dispatcher.
    """
    if settings.telegram.webhook_secret is None or not settings.telegram.webhook_url:
        raise ValueError(
            "TELEGRAM__WEBHOOK_URL and TELEGRAM__WEBHOOK_SECRET are required"
        )
    secret = settings.telegram.webhook_secret.get_secret_value()
    base_url = settings.telegram.webhook_url.rstrip("/")
    path = webhook_path(secret)

    async def on_startup(bot: Bot) -> None:
        await bot.set_webhook(
            f"{base_url}{path}",
            secret_token=secret,
            allowed_updates=allowed_updates(dispatcher, settings),
        )
        for key, other in extra:
            await other.set_webhook(
                f"{base_url}{bot_webhook_path(secret, key)}",
                secret_token=bot_secret_token(secret, key),
                allowed_updates=allowed_updates(dispatcher, settings),
            )

    dispatcher.startup.register(on_startup)
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher, bot=bot, secret_token=secret, container=container
    ).register(app, path=path)
    for key, other in extra:
        SimpleRequestHandler(
            dispatcher=dispatcher,
            bot=other,
            secret_token=bot_secret_token(secret, key),
            container=container,
        ).register(app, path=bot_webhook_path(secret, key))
    setup_application(app, dispatcher, bot=bot)
    return app


async def run_webhook(
    bot: Bot,
    dispatcher: Dispatcher,
    container: Any,
    settings: Settings,
    extra: Sequence[tuple[str, Bot]] = (),
) -> None:
    """Serve the webhook until the task is cancelled."""
    app = build_webhook_app(bot, dispatcher, container, settings, extra)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT).start()
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
