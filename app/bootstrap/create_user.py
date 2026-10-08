"""`python -m app create-user --role admin --login admin.x --email a@b.c`.

Creates an account waiting for activation and prints the one-time activation link
(the same link is emailed). Optional flags: `--first-name`, `--last-name`.
"""

import argparse
import asyncio
import sys

from app.bootstrap.common import build_container
from app.settings import Settings
from app.shared.actor import Role
from app.shared.logging import configure_logging

STAFF_ROLES = {role.value: role for role in Role if role is not Role.STUDENT}


def _names(extra: list[str], login: str) -> tuple[str, str]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--first-name", default="Administrator")
    parser.add_argument("--last-name", default=login)
    known = parser.parse_known_args(extra)[0]
    return str(known.first_name), str(known.last_name)


async def _create(settings: Settings, args: argparse.Namespace) -> str:
    role = STAFF_ROLES.get(args.role)
    if role is None:
        raise SystemExit(f"role must be one of: {', '.join(sorted(STAFF_ROLES))}")
    first_name, last_name = _names(args.extra, args.login)
    container = await build_container(settings, process="cli")
    try:
        created = await container.identity.auth.create_staff_account.execute(
            actor_id=None,
            last_name=last_name,
            first_name=first_name,
            middle_name=None,
            email=args.email,
            roles=[role],
            login=args.login,
        )
    finally:
        await container.close()
    return created.activation_url


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Create the account and print its activation link."""
    configure_logging(settings.log_level, json_logs=False)
    url = asyncio.run(_create(settings, args))
    sys.stdout.write(f"Activation link: {url}\n")
    return 0
