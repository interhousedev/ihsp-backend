"""Task notebooks.refresh_summaries (every minute): rebuild due notebook summaries."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.refresh_summaries")
async def refresh_summaries() -> int:
    """Return how many notebooks got a new title, emoji and summary (§ 3.2.6)."""
    return int(await get_container().notebooks.refresh_summaries.execute())
