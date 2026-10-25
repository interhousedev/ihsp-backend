"""links.release_slugs: free slugs revoked more than 90 days ago (daily)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="links.release_slugs")
async def release_slugs() -> int:
    """Return how many slugs were released."""
    return int(await get_container().links.release_slugs.execute())
