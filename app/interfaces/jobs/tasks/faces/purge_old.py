"""Task ``faces.purge_old``: drop device calls and passages past 7 days."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="faces.purge_old")
async def purge_old() -> int:
    """Run daily; returns how many rows were removed."""
    removed: int = await get_container().faces.purge_old.execute()
    return removed
