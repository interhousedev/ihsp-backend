"""Task ``identity.purge_deleted_users``: remove data of deleted accounts."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="identity.purge_deleted_users")
async def purge_deleted_users() -> int:
    """Run daily; returns how many accounts were anonymized (ID-29).

    Anonymize first, then close the pending deletions whose window ran out: their
    clean-up tasks (files, EMIS secret) run before the next day's anonymization.
    """
    container = get_container()
    count: int = await container.identity.auth.purge_deleted_users.execute()
    await container.identity.emis.finalize_account_deletions.execute()
    return count
