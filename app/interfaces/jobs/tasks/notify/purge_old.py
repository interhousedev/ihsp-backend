"""Task notify.purge_old: delete notifications older than 90 days."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notify.purge_old")
async def purge_old() -> int:
    """Daily at 03:30 Tashkent time; returns the number of deleted rows."""
    return int(await get_container().notify.purge_old.execute())
