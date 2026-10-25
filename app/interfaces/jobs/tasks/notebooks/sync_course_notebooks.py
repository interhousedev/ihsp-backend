"""Task notebooks.sync_course_notebooks: a course published a new revision."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.sync_course_notebooks")
async def sync_course_notebooks(course_id: UUID) -> int:
    """Start a sync of every student's notebook of the course; return how many."""
    return int(await get_container().notebooks.sync_course_notebooks.execute(course_id))
