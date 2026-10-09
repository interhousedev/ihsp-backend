"""Task library.process_item_file: extract, index and scan a file of an item."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.process_item_file", retry_on_error=True, max_retries=3)
async def process_item_file(item_id: UUID, file_id: UUID) -> None:
    """Text, outline, page count, hashes and scan findings; safe to repeat."""
    await get_container().library.catalogue.process_item_file.execute(item_id, file_id)
