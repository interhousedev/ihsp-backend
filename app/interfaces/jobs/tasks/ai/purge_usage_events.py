"""Task ai.purge_usage_events (daily): delete the expired usage events."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="ai.purge_usage_events")
async def purge_usage_events() -> int:
    """Delete the usage events older than AI__USAGE_RETENTION_DAYS; return the count."""
    return int(await get_container().ai.purge_usage_events.execute())
