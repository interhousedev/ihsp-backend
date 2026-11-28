"""Task `activities.media.purge`: remove expired staged and deleted club media."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.media.purge")
async def purge_media() -> int:
    """Return the number of items purged."""
    return int(await get_container().activities.media.purge())
