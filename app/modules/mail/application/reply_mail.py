"""Reply to a mail in the same thread (MAIL-4)."""

from uuid import UUID

from app.modules.mail.application.original_mail import LoadOriginal
from app.modules.mail.application.queue_outbound import OutboundRequest, QueueOutbound
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.outbound_message import reply_subject, thread_references


class ReplyMail:
    """Send an answer with In-Reply-To and References set."""

    def __init__(self, *, original: LoadOriginal, queue: QueueOutbound) -> None:
        """Store the dependencies."""
        self._original = original
        self._queue = queue

    async def execute(self, user_id: UUID, mail_id: UUID, *, html: str) -> MailMessage:
        """Reply to Reply-To or the sender; for a sent mail, to its recipients."""
        loaded = await self._original.load(user_id, mail_id)
        mail = loaded.mail
        if mail.is_inbound():
            reply_to = loaded.parsed.headers.reply_to if loaded.parsed else None
            recipients = [reply_to or mail.from_address]
        else:
            recipients = list(mail.to)
        request = OutboundRequest(
            to=recipients,
            subject=reply_subject(mail.subject),
            html=html,
            in_reply_to=mail.message_id,
            references=thread_references(mail.references, mail.message_id),
        )
        return await self._queue.execute(user_id, request)
