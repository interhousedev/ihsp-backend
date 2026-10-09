"""Task notebooks.sweep_auto_notebooks (twice an hour): safety net of the auto sync."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.sweep_auto_notebooks")
async def sweep_auto_notebooks() -> int:
    """Start a sync of the auto notebooks not synced for an hour; return how many."""
    return int(await get_container().notebooks.sweep_auto_notebooks.execute())
