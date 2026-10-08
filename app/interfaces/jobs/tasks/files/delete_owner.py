"""Task files.delete_owner: delete all files of a user now (account deletion)."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="files.delete_owner")
async def delete_owner(user_id: UUID) -> int:
    """Return how many files were deleted."""
    return int(await get_container().files.delete_owner_files.execute(user_id))
