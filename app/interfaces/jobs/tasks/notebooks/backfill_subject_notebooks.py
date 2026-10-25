"""Task notebooks.backfill_subject_notebooks (daily): queue each student's check."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.backfill_subject_notebooks")
async def backfill_subject_notebooks() -> int:
    """Queue one provisioning task per student; return how many students."""
    result = await get_container().notebooks.backfill_subject_notebooks.execute()
    return result.students
