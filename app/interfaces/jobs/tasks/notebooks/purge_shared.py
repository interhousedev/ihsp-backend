"""Task notebooks.purge_shared (daily 04:45): unused shared texts and cached results."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.purge_shared")
async def purge_shared() -> dict[str, int]:
    """Return how many documents and cache rows were removed."""
    return await get_container().notebooks.purge_shared.execute()
