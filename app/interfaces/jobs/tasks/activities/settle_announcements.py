"""Task `activities.settle_announcements`: send or close announcements that are due."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.settle_announcements")
async def settle_announcements() -> int:
    """Return the number of items handled."""
    return int(await get_container().activities.announcements.settle_due())
