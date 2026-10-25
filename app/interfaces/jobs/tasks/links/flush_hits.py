"""links.flush_hits: move click counters from Redis to PostgreSQL (every 5 min)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="links.flush_hits")
async def flush_hits() -> int:
    """Return how many links received new clicks."""
    return int(await get_container().links.flush_hits.execute())
