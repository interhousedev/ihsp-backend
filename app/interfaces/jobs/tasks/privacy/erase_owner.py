"""Task ``privacy.erase_owner``: erase a closed account's personal data."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="privacy.erase_owner")
async def erase_owner(user_id: UUID) -> int:
    """Return how many rows were deleted or cleared."""
    return int(await get_container().privacy.erase_owner.execute(user_id))
