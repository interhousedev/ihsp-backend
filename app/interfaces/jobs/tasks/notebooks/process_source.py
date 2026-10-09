"""Task notebooks.process_source: read, chunk and store the passages of a source."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.process_source", retry_on_error=True, max_retries=3)
async def process_source(source_id: UUID) -> None:
    """Run the source pipeline (§ 3.2.2); repeated runs are harmless."""
    await get_container().notebooks.process_source.execute(source_id)
