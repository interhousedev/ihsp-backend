"""library.delete_owner: erase the private library data of a closed account."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.delete_owner")
async def delete_owner(user_id: UUID) -> int:
    """Delete shelf, progress and notes; withdraw unfinished uploads (§ 8.1)."""
    library = get_container().library
    deleted = int(await library.reader.delete_owner.execute(user_id))
    return deleted + int(await library.materials.delete_owner.execute(user_id))
