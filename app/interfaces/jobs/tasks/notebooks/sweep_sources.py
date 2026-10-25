"""Task notebooks.sweep_sources (daily 03:30): deleted files and outdated sources."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.sweep_sources")
async def sweep_sources() -> int:
    """FILE-6: drop the text of deleted files; mark outdated sources; return changes."""
    return int(await get_container().notebooks.sweep_sources.execute())
