"""Task mail.check_bounces (hourly): suspend mailboxes with a bounce spike."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="mail.check_bounces")
async def check_bounces() -> None:
    """Suspend users with at least five bounces in 24 hours."""
    await get_container().mail.check_bounces.execute()
