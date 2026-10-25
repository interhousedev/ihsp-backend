"""Task mail.parse_inbound: parse a received mail and notify the student."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="mail.parse_inbound", retry_on_error=True, max_retries=3)
async def parse_inbound(mail_id: UUID) -> None:
    """Parse once; repeated runs are harmless."""
    await get_container().mail.parse_inbound.execute(mail_id)
