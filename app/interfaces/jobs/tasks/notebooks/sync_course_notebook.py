"""Task notebooks.sync_course_notebook: bring one course notebook up to date."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="notebooks.sync_course_notebook",
    retry_on_error=True,
    max_retries=3,
)
async def sync_course_notebook(notebook_id: UUID) -> int:
    """Add, drop and refresh the materials of the notebook; return what changed."""
    result = await get_container().notebooks.sync_course_notebook.execute(notebook_id)
    return result.added + result.removed + result.refreshed
