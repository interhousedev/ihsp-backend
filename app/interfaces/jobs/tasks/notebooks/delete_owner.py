"""Task notebooks.delete_owner: delete all notebooks of a user (account deletion)."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.delete_owner")
async def delete_owner(user_id: UUID) -> int:
    """NB-15: return how many notebooks were deleted."""
    return int(await get_container().notebooks.delete_owner.execute(user_id))
