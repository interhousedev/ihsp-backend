"""Task notebooks.extract_source_vision: the model reads a scanned file."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="notebooks.extract_source_vision", retry_on_error=True, max_retries=2
)
async def extract_source_vision(source_id: UUID) -> None:
    """Read the scanned file with the model; failures are kept on the source."""
    await get_container().notebooks.extract_source_vision.execute(source_id)
