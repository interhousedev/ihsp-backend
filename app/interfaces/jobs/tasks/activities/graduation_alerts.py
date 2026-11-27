"""Task `activities.graduation_alerts`: tell graduating club owners to hand over."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.graduation_alerts")
async def graduation_alerts() -> int:
    """Return the number of items handled."""
    return int(await get_container().activities.ownership.graduation_alerts())
