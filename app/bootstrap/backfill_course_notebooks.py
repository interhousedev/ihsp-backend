"""`python -m app backfill-course-notebooks`: course notebooks for existing students.

Creates and fills the missing notebook of every enrollment in a published course.
Idempotent: run it again any time.
"""

import argparse
import asyncio
import sys

from app.bootstrap.common import build_container
from app.settings import Settings
from app.shared.logging import configure_logging


async def _backfill(settings: Settings) -> tuple[int, int]:
    container = await build_container(settings, process="cli")
    try:
        result = await container.notebooks.backfill_course_notebooks.execute(
            inline=True
        )
    finally:
        await container.close()
    return result.enrollments, result.created


def run(settings: Settings, args: argparse.Namespace) -> int:
    """Run the backfill and print how many notebooks were created."""
    configure_logging(settings.log_level, json_logs=False)
    enrollments, created = asyncio.run(_backfill(settings))
    sys.stdout.write(f"Enrollments: {enrollments}, notebooks created: {created}\n")
    return 0
