"""Task library.backfill_covers: covers for books that have none."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.backfill_covers", retry_on_error=False)
async def backfill_covers(limit: int = 500) -> int:
    """Cut covers out of the files of up to `limit` books; safe to repeat."""
    return await get_container().library.catalogue.backfill_covers.execute(limit=limit)
