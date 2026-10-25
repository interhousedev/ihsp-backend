"""Task notebooks.label_sources: topic labels for the selected sources (G12/G13)."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.label_sources")
async def label_sources(notebook_id: UUID) -> None:
    """Run the labeling; failures mark the run `failed` and never raise."""
    await get_container().notebooks.label_sources.execute(notebook_id)
