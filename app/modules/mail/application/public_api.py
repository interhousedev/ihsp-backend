"""MailApi: what the bot may do with a mailbox (contract in shared/contracts)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.mail.application.config import MailConfig
from app.modules.mail.application.forward_mail import ForwardMail
from app.modules.mail.application.mark_spam import MarkSpam
from app.modules.mail.application.recent_mail import RecentMail
from app.modules.mail.application.reply_mail import ReplyMail
from app.modules.mail.application.send_mail import SendMail
from app.modules.mail.application.view_mail import ViewMail
from app.modules.mail.domain.addresses import mailbox_address
from app.shared.clock import Clock
from app.shared.contracts.mail import MailSummary


class MailApiImpl:
    """Implements ``MailApi`` over the module's use cases."""

    def __init__(
        self,
        *,
        recent: RecentMail,
        view: ViewMail,
        send: SendMail,
        reply: ReplyMail,
        forward: ForwardMail,
        mark_spam: MarkSpam,
        clock: Clock,
        config: MailConfig,
    ) -> None:
        """Store the use cases."""
        self._recent = recent
        self._view = view
        self._send = send
        self._reply = reply
        self._forward = forward
        self._mark_spam = mark_spam
        self._clock = clock
        self._config = config

    async def recent(
        self, user_id: UUID, *, limit: int = 10, before: datetime | None = None
    ) -> list[MailSummary]:
        """Return the newest mails of the user (spam is hidden)."""
        return await self._recent.execute(user_id, limit=limit, before=before)

    async def view(self, user_id: UUID, mail_id: UUID) -> dict[str, Any]:
        """Return summary, text, Telegram HTML, attachments and the truncated flag."""
        view = await self._view.execute(user_id, mail_id)
        return {
            "summary": view.summary,
            "text": view.text,
            "html_telegram": view.html_telegram,
            "attachments": view.attachments,
            "truncated": view.truncated,
            "skipped_attachments": view.skipped_attachments,
        }

    async def send(
        self, user_id: UUID, *, to: Sequence[str], subject: str, html: str
    ) -> MailSummary:
        """Queue a new mail."""
        mail = await self._send.execute(user_id, to=to, subject=subject, html=html)
        return mail.summary(self._clock.now())

    async def reply(self, user_id: UUID, mail_id: UUID, *, html: str) -> MailSummary:
        """Queue a reply in the same thread."""
        mail = await self._reply.execute(user_id, mail_id, html=html)
        return mail.summary(self._clock.now())

    async def forward(
        self,
        user_id: UUID,
        mail_id: UUID,
        *,
        to: Sequence[str],
        note_html: str | None,
    ) -> MailSummary:
        """Queue a forward with the original attachments."""
        mail = await self._forward.execute(user_id, mail_id, to=to, note_html=note_html)
        return mail.summary(self._clock.now())

    async def mark_spam(self, user_id: UUID, mail_id: UUID, *, spam: bool) -> None:
        """Mark the mail as spam, or take the mark back."""
        await self._mark_spam.execute(user_id, mail_id, spam=spam)

    def address_of(self, login: str) -> str:
        """Return the mailbox address of a login."""
        return mailbox_address(login, self._config.mail_domain)
