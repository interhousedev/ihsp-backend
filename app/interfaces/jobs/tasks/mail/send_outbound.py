"""Task mail.send_outbound: deliver a queued mail through the relay."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="mail.send_outbound", retry_on_error=True, max_retries=2)
async def send_outbound(mail_id: UUID) -> None:
    """Send once; the use case retries the relay itself and records the result."""
    await get_container().mail.deliver_outbound.execute(mail_id)
