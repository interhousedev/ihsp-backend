"""Task files.purge_pending: remove abandoned and rejected uploads (hourly)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="files.purge_pending")
async def purge_pending() -> int:
    """Return how many rows were removed."""
    return int(await get_container().files.purge_pending.execute())
