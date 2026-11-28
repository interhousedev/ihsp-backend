"""`python -m app backfill-emis-attendance`: attendance history from EMIS.

Runs the silent backfill sync (semesters 1 to 4: marks, results and per-lesson
attendance) for every active, already imported student, or for the ids given with
``--user``. Sends no notifications; the scheduled `academic.sync_all` keeps the
current semester fresh and notifies new absences. Idempotent: run it again any time.
Prints counts only.
"""

import argparse
import asyncio
import sys
from collections import Counter
from uuid import UUID

from app.bootstrap.common import build_container
from app.bootstrap.container import Container
from app.modules.academic.infrastructure.orm.student import Student
from app.settings import Settings
from app.shared.logging import configure_logging

import sqlalchemy as sa
import structlog

log = structlog.get_logger(__name__)


async def _student_ids(container: Container, given: list[UUID]) -> list[UUID]:
    if given:
        return given
    stmt = (
        sa.select(Student.user_id)
        .where(Student.status == "active", Student.backfilled_at.is_not(None))
        .order_by(Student.user_id)
    )
    async with container.sessionmaker() as session:
        return list((await session.execute(stmt)).scalars())


async def _backfill(settings: Settings, given: list[UUID]) -> Counter[str]:
    from app.interfaces.jobs.broker import broker

    await broker.startup()
    container = await build_container(settings, process="cli")
    counts: Counter[str] = Counter()
    try:
        backfill = container.academic.marks.backfill_student
        for user_id in await _student_ids(container, given):
            try:
                outcome = await backfill.execute(user_id)
                counts[outcome.status] += 1
            except Exception:
                log.exception("emis_attendance_backfill_failed", user_id=str(user_id))
                counts["failed"] += 1
        return counts
    finally:
        await container.close()
        await broker.shutdown()


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Run the backfill and print the counts; exit 1 when any student failed."""
    parser = argparse.ArgumentParser(prog="python -m app backfill-emis-attendance")
    parser.add_argument("--user", action="append", type=UUID, default=[])
    options = parser.parse_args(args.extra)
    configure_logging(settings.log_level, json_logs=False)
    counts = asyncio.run(_backfill(settings, options.user))
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"
    sys.stdout.write(f"EMIS attendance backfill: {summary}\n")
    return 1 if counts["failed"] else 0
