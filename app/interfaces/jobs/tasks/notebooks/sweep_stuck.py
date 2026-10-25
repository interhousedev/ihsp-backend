"""Task notebooks.sweep_stuck (every 10 minutes): rescue stuck sources and outputs."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.sweep_stuck")
async def sweep_stuck() -> dict[str, int]:
    """Re-kick stuck sources and queued outputs, time out generating ones."""
    return dict(await get_container().notebooks.sweep_stuck.execute())
