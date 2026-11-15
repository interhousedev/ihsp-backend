"""Task library.reindex_item_pages: rebuild the stored page text of one file."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.reindex_item_pages", retry_on_error=True, max_retries=3)
async def reindex_item_pages(item_id: UUID, file_id: UUID) -> bool:
    """Replace the pages, folded text and word boxes of a file; safe to repeat."""
    return await get_container().library.catalogue.reindex_item_pages.execute(
        item_id, file_id
    )
