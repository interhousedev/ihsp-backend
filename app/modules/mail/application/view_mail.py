"""Show one mail: text, Telegram HTML and attachments (UF-MAIL-01, UF-MAIL-02)."""

import asyncio
from dataclasses import dataclass, field, replace
from uuid import UUID

from app.modules.mail.application.original_mail import LoadOriginal
from app.modules.mail.domain.inbound_message import ParsedMail
from app.modules.mail.domain.telegram_html import (
    TelegramText,
    html_to_telegram,
    plain_to_telegram,
)
from app.shared.clock import Clock
from app.shared.contracts.files import FileRef, FilesApi
from app.shared.contracts.mail import MailSummary

MAX_TEXT = 200_000


@dataclass(frozen=True, slots=True)
class MailView:
    """What the bot needs to render a mail."""

    summary: MailSummary
    text: str = ""
    html_telegram: str = ""
    attachments: list[FileRef] = field(default_factory=list)
    truncated: bool = False
    skipped_attachments: list[str] = field(default_factory=list)


def telegram_body(parsed: ParsedMail) -> TelegramText:
    """HTML body converted to Telegram HTML, else the escaped text body."""
    if parsed.html:
        return html_to_telegram(parsed.html)
    return plain_to_telegram(parsed.text or "")


def render(parsed: ParsedMail) -> tuple[TelegramText, str]:
    """The Telegram body and the plain text (CPU work: run it in a thread)."""
    return telegram_body(parsed), parsed.plain_text()[:MAX_TEXT]


class ViewMail:
    """Parse the raw mail again; a deleted raw mail gives the summary only."""

    def __init__(
        self, *, original: LoadOriginal, files: FilesApi, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._original = original
        self._files = files
        self._clock = clock

    async def execute(self, user_id: UUID, mail_id: UUID) -> MailView:
        """Return the view; raises MailNotFoundError for a mail of another mailbox."""
        loaded = await self._original.load(user_id, mail_id)
        summary = loaded.mail.summary(self._clock.now())
        if loaded.parsed is None:
            return MailView(summary=replace(summary, purged=True))
        body, text = await asyncio.to_thread(render, loaded.parsed)
        refs = await self._files.get_many(loaded.mail.attachment_file_ids)
        attachments = [
            refs[file_id]
            for file_id in loaded.mail.attachment_file_ids
            if file_id in refs and refs[file_id].status != "deleted"
        ]
        return MailView(
            summary=summary,
            text=text,
            html_telegram=body.html,
            attachments=attachments,
            truncated=body.truncated,
            skipped_attachments=list(loaded.mail.meta.skipped_attachments),
        )
