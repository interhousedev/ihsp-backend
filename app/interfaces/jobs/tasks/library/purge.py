"""library.purge: delete files of old rejected and withdrawn materials (daily)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.purge")
async def purge() -> int:
    """Return how many files were deleted."""
    return int(await get_container().library.materials.purge_files.execute())
