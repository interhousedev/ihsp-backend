"""Task ``privacy.cleanup_exports``: delete archives whose link expired (hourly)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="privacy.cleanup_exports")
async def cleanup_exports() -> int:
    """Return how many archives were deleted."""
    return int(await get_container().privacy.cleanup_exports.execute())
