"""Task `activities.rate_events`: ask attendees to rate events that ended."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.rate_events")
async def rate_events() -> int:
    """Return the number of items handled."""
    return int(await get_container().activities.events.rate_due())
