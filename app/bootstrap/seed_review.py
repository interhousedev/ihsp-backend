"""`python -m app seed-review`: public test accounts for the ChatGPT app review.

Safe on production: it only creates or resets the three review accounts and the
made-up data around them, and reruns change nothing that is already right.
"""

import argparse
import asyncio
import sys

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.bootstrap.seed.review_accounts import REVIEW_ACCOUNTS, ensure_review_accounts
from app.bootstrap.seed.review_data import seed_review_data
from app.settings import Settings
from app.shared.logging import configure_logging


def out(message: str) -> None:
    """Write a line to stdout."""
    sys.stdout.write(message + "\n")


async def seed(container: Container) -> None:
    """Create the accounts, then their data."""
    auth = container.identity.auth
    ids = await ensure_review_accounts(auth.uow_factory, auth.hasher, container.clock)
    await seed_review_data(container, ids)


async def _run(settings: Settings) -> None:
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process="cli")
    try:
        await seed(container)
    finally:
        await container.close()
        await broker.shutdown()


def describe() -> None:
    """Print the logins and the MCP server each one covers (passwords: the docs)."""
    out("Review accounts (passwords are in docs/chatgpt-review.md):")
    for account in REVIEW_ACCOUNTS:
        out(f"  {account.login}  ->  MCP server: {', '.join(account.servers)}")


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Seed the review accounts and data; running it again is harmless."""
    configure_logging(settings.log_level, json_logs=False)
    asyncio.run(_run(settings))
    describe()
    return 0
