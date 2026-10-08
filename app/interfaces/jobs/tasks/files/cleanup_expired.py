"""Task files.cleanup_expired: delete expired files (daily 03:00 Asia/Tashkent)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="files.cleanup_expired")
async def cleanup_expired() -> int:
    """Return how many files were deleted."""
    return int(await get_container().files.cleanup_expired.execute())
