"""Task library.backfill_item_pages: queue a reindex of files with old page rows."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.backfill_item_pages", retry_on_error=False)
async def backfill_item_pages(limit: int = 1000) -> int:
    """Queue `library.reindex_item_pages` for up to `limit` files; safe to repeat."""
    return await get_container().library.catalogue.backfill_item_pages.execute(
        limit=limit
    )
