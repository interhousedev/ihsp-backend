"""The mail process: the inbound SMTP server (port 2525 in development)."""

import argparse
import asyncio

from app.bootstrap.common import build_container
from app.interfaces.smtp.server import run_mail_server
from app.settings import Settings
from app.shared.logging import configure_logging


async def _serve(settings: Settings) -> None:
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process="mail")
    try:
        await run_mail_server(container)
    finally:
        await container.close()
        await broker.shutdown()


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Receive mail until interrupted."""
    configure_logging(settings.log_level, json_logs=settings.env == "prod")
    asyncio.run(_serve(settings))
    return 0
