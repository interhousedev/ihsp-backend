"""Task notebooks.gather_web_materials: the linked files of a ready web source."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.gather_web_materials", retry_on_error=False)
async def gather_web_materials(source_id: UUID) -> None:
    """Gather once; a repeated run skips the files the notebook already has."""
    await get_container().notebooks.gather_web_materials.execute(source_id)
