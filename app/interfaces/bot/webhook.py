"""Webhook mode: an aiohttp server that feeds Telegram updates to the dispatcher."""

import asyncio
from typing import Any

from app.settings import Settings

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

WEBHOOK_HOST = "0.0.0.0"  # the process runs in a container behind nginx
WEBHOOK_PORT = 8002


def webhook_path(secret: str) -> str:
    """The route Telegram posts to; the secret is part of it."""
    return f"/telegram/{secret}"


def build_webhook_app(
    bot: Bot, dispatcher: Dispatcher, container: Any, settings: Settings
) -> web.Application:
    """Build the aiohttp app; Telegram must send the secret token header."""
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
            allowed_updates=dispatcher.resolve_used_update_types(),
        )

    dispatcher.startup.register(on_startup)
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher, bot=bot, secret_token=secret, container=container
    ).register(app, path=path)
    setup_application(app, dispatcher, bot=bot)
    return app


async def run_webhook(
    bot: Bot, dispatcher: Dispatcher, container: Any, settings: Settings
) -> None:
    """Serve the webhook until the task is cancelled."""
    app = build_webhook_app(bot, dispatcher, container, settings)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT).start()
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
