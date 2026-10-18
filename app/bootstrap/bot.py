"""The Telegram bot process: long polling in development, webhook in production."""

import argparse
import asyncio

from app.bootstrap.common import build_container
from app.interfaces.bot.main import run_bot
from app.settings import Settings
from app.shared.logging import configure_logging
from app.shared.observability import init_observability


async def _serve(settings: Settings) -> None:
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process="bot")
    try:
        await run_bot(container)
    finally:
        await container.close()
        await broker.shutdown()


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Run the bot until interrupted."""
    configure_logging(settings.log_level, json_logs=settings.env == "prod")
    init_observability(settings, "bot")
    asyncio.run(_serve(settings))
    return 0
