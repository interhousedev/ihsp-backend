"""Task ``academic.generate_lessons``: expand the timetable into lessons.

Scheduled daily at 02:00 by the scheduler and kicked after timetable and term
changes with ``term_id`` and ``from_date``.
"""

import datetime as dt
from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.generate_lessons")
async def generate_lessons(
    term_id: str | None = None, from_date: str | None = None, days: int = 14
) -> int:
    """Generate lessons for the next days; return how many lessons changed."""
    container = get_container()
    changed: int = await container.academic.schedule.generate_lessons.execute(
        term_id=UUID(term_id) if term_id else None,
        from_date=dt.date.fromisoformat(from_date) if from_date else None,
        days=days,
    )
    return changed
