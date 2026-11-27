"""Task `activities.expire_transfers`: close club ownership offers past their time."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.expire_transfers")
async def expire_transfers() -> int:
    """Return the number of items handled."""
    return int(await get_container().activities.ownership.expire_due())
