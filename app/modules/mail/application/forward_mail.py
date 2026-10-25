"""Forward a mail with its attachments (MAIL-2, MAIL-4)."""

import asyncio
from collections.abc import Sequence
from uuid import UUID

from app.modules.mail.application.original_mail import LoadOriginal
from app.modules.mail.application.queue_outbound import OutboundRequest, QueueOutbound
from app.modules.mail.domain.errors import MailPurgedError
from app.modules.mail.domain.inbound_message import Attachment, ParsedMail
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.outbound_message import forward_body_html, forward_subject
from app.modules.mail.domain.telegram_html import html_to_telegram, plain_to_telegram
from app.shared.contracts.files import FilesApi


def original_body_html(parsed: ParsedMail) -> str:
    """The whole original body as Telegram-style HTML (no length limit)."""
    if parsed.html:
        return html_to_telegram(parsed.html, limit=None).html
    return plain_to_telegram(parsed.text or "", limit=None).html


class ForwardMail:
    """Quote the original with its headers and attach its stored attachments."""

    def __init__(
        self, *, original: LoadOriginal, queue: QueueOutbound, files: FilesApi
    ) -> None:
        """Store the dependencies."""
        self._original = original
        self._queue = queue
        self._files = files

    async def execute(
        self,
        user_id: UUID,
        mail_id: UUID,
        *,
        to: Sequence[str],
        note_html: str | None,
    ) -> MailMessage:
        """Queue the forward; a mail whose raw file is gone cannot be forwarded."""
        loaded = await self._original.load(user_id, mail_id)
        if loaded.parsed is None:
            raise MailPurgedError()
        mail = loaded.mail
        html = forward_body_html(
            note_html,
            from_address=mail.from_address,
            sent_at=mail.occurred_at,
            subject=mail.subject,
            to=mail.to,
            original_html=await asyncio.to_thread(original_body_html, loaded.parsed),
        )
        request = OutboundRequest(
            to=to,
            subject=forward_subject(mail.subject),
            html=html,
            attachments=await self._attachments(mail),
        )
        return await self._queue.execute(user_id, request)

    async def _attachments(self, mail: MailMessage) -> list[Attachment]:
        refs = await self._files.get_many(mail.attachment_file_ids)
        found: list[Attachment] = []
        for file_id in mail.attachment_file_ids:
            ref = refs.get(file_id)
            if ref is None or ref.status == "deleted":
                continue
            data = await self._files.read_bytes(file_id)
            found.append(Attachment(ref.name, ref.content_type, data))
        return found
