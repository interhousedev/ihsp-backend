"""Task notebooks.sync_auto_notebook: bring a subject or lesson notebook up to date."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="notebooks.sync_auto_notebook", retry_on_error=True, max_retries=3
)
async def sync_auto_notebook(notebook_id: UUID) -> dict[str, int]:
    """Add new lesson materials, drop those the student can no longer see."""
    result = await get_container().notebooks.sync_auto_notebook.execute(notebook_id)
    return {
        "added": result.added,
        "removed": result.removed,
        "skipped": result.skipped,
    }
