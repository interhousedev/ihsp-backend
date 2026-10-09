"""Task notebooks.purge_deleted (daily 04:15): remove notebooks deleted 7 days ago."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.purge_deleted")
async def purge_deleted() -> int:
    """Return how many notebooks were removed for good."""
    return int(await get_container().notebooks.purge_deleted.execute())
