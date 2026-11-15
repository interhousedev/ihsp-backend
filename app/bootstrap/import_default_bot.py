"""`python -m app import-default-bot`: store the env bot token in Vault as default.

One-shot and idempotent. Run it in a container that holds `TELEGRAM__BOT_TOKEN`
and the bot_vault AppRole (the api service); once it reports success the
`TELEGRAM__BOT_TOKEN` line can leave `.env.prod`: the bot, api, worker and
identity then read the default bot's token from Vault. The token is never printed.
"""

import argparse
import asyncio
import sys
from typing import TextIO

from app.bootstrap.common import build_container
from app.modules.admin.application.bot_admin import BotAdmin
from app.settings import DEV_BOT_TOKEN, Settings
from app.shared.logging import configure_logging


async def import_env_bot(
    admin: BotAdmin, token: str, username: str, out: TextIO
) -> int:
    """Import the env bot, report the outcome (never the token), return the code."""
    if not token or token == DEV_BOT_TOKEN:
        out.write("TELEGRAM__BOT_TOKEN is not set; nothing to import\n")
        return 1
    bot = await admin.import_env_bot(token, username)
    if bot is None:
        out.write(
            "import failed: Vault unreachable, malformed token, or this Telegram bot"
            " is registered but not as the default bot (see the log)\n"
        )
        return 1
    out.write(f"default bot {bot.id} (@{bot.username}): token stored in Vault\n")
    return 0


async def _import(settings: Settings) -> int:
    container = await build_container(settings, process="cli")
    try:
        return await import_env_bot(
            container.admin.bot_admin,
            settings.telegram.bot_token.get_secret_value(),
            settings.telegram.bot_username,
            sys.stdout,
        )
    finally:
        await container.close()


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Import the env bot token into Vault as the default bot."""
    configure_logging(settings.log_level, json_logs=False)
    return asyncio.run(_import(settings))
