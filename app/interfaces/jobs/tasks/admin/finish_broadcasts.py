"""Task admin.finish_broadcasts: close broadcasts that were fully delivered."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admin.finish_broadcasts")
async def finish_broadcasts() -> int:
    """Every 5 minutes; returns the number of broadcasts that finished."""
    return int(await get_container().admin.finish_broadcasts.execute())
