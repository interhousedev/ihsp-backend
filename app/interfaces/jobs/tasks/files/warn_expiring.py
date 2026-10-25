"""Task files.warn_expiring: warn about files that expire soon (daily 10:00)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="files.warn_expiring")
async def warn_expiring() -> int:
    """Return how many notifications were queued."""
    return int(await get_container().files.warn_expiring.execute())
