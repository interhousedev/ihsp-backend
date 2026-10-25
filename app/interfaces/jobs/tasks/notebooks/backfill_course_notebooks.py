"""Task notebooks.backfill_course_notebooks: queue a notebook check per enrollment."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.backfill_course_notebooks")
async def backfill_course_notebooks() -> int:
    """Queue one provisioning task per enrollment; return how many enrollments."""
    result = await get_container().notebooks.backfill_course_notebooks.execute()
    return result.enrollments
