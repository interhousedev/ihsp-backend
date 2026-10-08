"""Task ``identity.purge_deleted_users``: remove data of deleted accounts."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="identity.purge_deleted_users")
async def purge_deleted_users() -> int:
    """Run daily; returns how many accounts were anonymized (ID-29)."""
    container = get_container()
    count: int = await container.identity.auth.purge_deleted_users.execute()
    return count
