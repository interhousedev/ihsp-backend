"""Task notebooks.sync_lesson_notebooks: a lesson's materials changed."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.sync_lesson_notebooks")
async def sync_lesson_notebooks(lesson_id: UUID) -> int:
    """Start a sync of every auto notebook that feeds on the lesson; return how many."""
    return int(await get_container().notebooks.sync_lesson_notebooks.execute(lesson_id))
