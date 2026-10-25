"""`python -m app seed-demo`: demo data for development (idempotent)."""

import argparse
import asyncio
import sys

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.bootstrap.seed.content import seed_broadcast, seed_course, seed_flashcards
from app.bootstrap.seed.groups import finish_groups
from app.bootstrap.seed.homework import demo_student_ids, seed_homework
from app.bootstrap.seed.library import seed_library
from app.bootstrap.seed.notebooks import seed_notebook
from app.bootstrap.seed.schedule import generate_lessons, seed_structure
from app.bootstrap.seed.students import (
    EMIS_LOGINS,
    register_students,
)
from app.bootstrap.seed.users import (
    ADMIN_LOGIN,
    LIBRARIAN_LOGIN,
    TEACHERS,
    ensure_admin,
    ensure_teachers,
)
from app.modules.identity.application.register_ports import CredentialStore
from app.modules.identity.domain.login_name import base_login
from app.modules.identity.infrastructure.emis.fake import FAKE_STUDENTS
from app.settings import Settings
from app.shared.logging import configure_logging
from app.shared.text import title_case

import structlog

log = structlog.get_logger(__name__)

FAKE_BY_LOGIN = {student.login: student for student in FAKE_STUDENTS}


MASK = "********"


def out(message: str) -> None:
    """Write a line to stdout."""
    sys.stdout.write(message + "\n")


async def seed(
    container: Container, credentials: CredentialStore | None = None
) -> None:
    """Run every seed step in dependency order (``credentials`` replaces Vault)."""
    admin_id = await ensure_admin(container)
    teachers = await ensure_teachers(container)
    structure = await seed_structure(container, teachers)
    await register_students(container, credentials)
    await finish_groups(container, structure, teachers)
    changed = await generate_lessons(container, structure.term)
    log.info("seed_lessons_generated", changed=changed)
    await seed_homework(container, await demo_student_ids(container))
    first_group = next(iter(structure.group_ids.values()))
    members = await container.academic.schedule.queries.group_user_ids([first_group])
    if members:
        await seed_flashcards(container, members[0])
        await seed_notebook(container, members[0])
    await seed_course(container, admin_id)
    await seed_broadcast(container, admin_id)
    await seed_library(container, structure.subject_ids, structure.group_ids)


def describe() -> None:
    """Tell where the demo accounts are."""
    # Passwords are shown masked; the demo values are in this module's constants.
    out(f"admin:    {ADMIN_LOGIN} / {MASK} (code arrives in Mailpit)")
    for spec in TEACHERS:
        out(f"teacher:  {spec.login} / {MASK}")
    out(f"librarian: {LIBRARIAN_LOGIN} / {MASK} (when the library is on)")
    for emis_login in EMIS_LOGINS:
        student = FAKE_BY_LOGIN[emis_login]
        login = base_login(
            title_case(student.last_name), title_case(student.first_name)
        )
        out(f"student:  {login} / {MASK} (EMIS login {emis_login})")


async def _run(settings: Settings) -> None:
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process="cli")
    try:
        await seed(container)
    finally:
        await container.close()
        await broker.shutdown()


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Create the demo data; running it again changes nothing that exists."""
    configure_logging(settings.log_level, json_logs=False)
    asyncio.run(_run(settings))
    describe()
    return 0
