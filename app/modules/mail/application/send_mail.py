"""Send a new email from the student's mailbox (MAIL-4, MAIL-6)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.mail.application.queue_outbound import OutboundRequest, QueueOutbound
from app.modules.mail.domain.mail_message import MailMessage


class SendMail:
    """Compose a mail from recipients, subject and Telegram-style HTML."""

    def __init__(self, *, queue: QueueOutbound) -> None:
        """Store the shared outbound queue."""
        self._queue = queue

    async def execute(
        self, user_id: UUID, *, to: Sequence[str], subject: str, html: str
    ) -> MailMessage:
        """Validate, apply limits and queue the mail for delivery."""
        request = OutboundRequest(to=to, subject=subject.strip(), html=html)
        return await self._queue.execute(user_id, request)
