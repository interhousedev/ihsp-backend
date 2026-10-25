"""Task admin.start_scheduled_broadcasts: start broadcasts whose time has come."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admin.start_scheduled_broadcasts")
async def start_scheduled_broadcasts() -> int:
    """Every minute; returns the number of broadcasts that started."""
    return int(await get_container().admin.start_scheduled_broadcasts.execute())
