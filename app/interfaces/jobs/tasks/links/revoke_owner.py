"""links.revoke_owner: revoke every link of a closed account."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="links.revoke_owner")
async def revoke_owner(user_id: UUID) -> int:
    """Return how many links were revoked."""
    return int(await get_container().links.revoke_owner.execute(user_id))
