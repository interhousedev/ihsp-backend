"""Task mail.sweep (every 10 minutes): restart unfinished parsing and sending."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="mail.sweep")
async def sweep() -> None:
    """Kick again inbound mails not parsed and outbound mails not sent."""
    await get_container().mail.sweep_mail.execute()
