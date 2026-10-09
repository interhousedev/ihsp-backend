"""library.rollup_stats: move the Redis counters into `item_stats` (daily 02:10)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.rollup_stats")
async def rollup_stats() -> int:
    """Return how many item-days were written."""
    return int(await get_container().library.taxonomy.rollup_stats.execute())
