"""Task mail.purge (daily): delete old spam, flag mails older than 30 days."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="mail.purge")
async def purge() -> None:
    """Run the daily cleanup of the mailboxes."""
    await get_container().mail.purge_mail.execute()
