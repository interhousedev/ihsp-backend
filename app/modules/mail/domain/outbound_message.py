"""Building outbound messages (MAIL-4, MAIL-6)."""

import html as html_lib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime
from uuid import UUID

from app.modules.mail.domain.inbound_message import Attachment
from app.modules.mail.domain.telegram_html import (
    html_to_text,
    telegram_to_email_html,
)

MAX_OUTBOUND_BYTES = 25 * 1024 * 1024
MAX_REFERENCES = 20


@dataclass(frozen=True, slots=True)
class OutboundDraft:
    """Everything needed to build one outbound message."""

    display_name: str
    login: str
    domain: str
    to: Sequence[str]
    subject: str
    html: str
    message_id: str
    sent_at: datetime
    in_reply_to: str | None = None
    references: Sequence[str] = ()
    attachments: Sequence[Attachment] = ()


def new_message_id(mail_id: UUID, domain: str) -> str:
    """Return a unique Message-ID in the mail domain."""
    return f"<{mail_id.hex}@{domain}>"


def reply_subject(subject: str) -> str:
    """Prefix 'Re: ' unless the subject already has it."""
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def forward_subject(subject: str) -> str:
    """Prefix 'Fwd: ' unless the subject already has it."""
    return subject if subject.lower().startswith(("fwd:", "fw:")) else f"Fwd: {subject}"


def thread_references(
    original_references: Sequence[str], original_message_id: str
) -> list[str]:
    """References of a reply: the original's references plus its Message-ID."""
    chain = [*original_references, original_message_id]
    return chain[-MAX_REFERENCES:]


def _wrap_html(body: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        f"<body>{body}</body></html>"
    )


def build_message(draft: OutboundDraft) -> bytes:
    """Return the message as bytes with CRLF line endings, ready for the relay."""
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = Address(
        display_name=draft.display_name, username=draft.login, domain=draft.domain
    )
    msg["To"] = ", ".join(draft.to)
    msg["Subject"] = draft.subject
    msg["Date"] = format_datetime(draft.sent_at)
    msg["Message-ID"] = draft.message_id
    if draft.in_reply_to:
        msg["In-Reply-To"] = draft.in_reply_to
    if draft.references:
        msg["References"] = " ".join(draft.references)
    html_body = telegram_to_email_html(draft.html)
    msg.set_content(html_to_text(html_body) or " ")
    msg.add_alternative(_wrap_html(html_body), subtype="html")
    for item in draft.attachments:
        maintype, _, subtype = item.content_type.partition("/")
        msg.add_attachment(
            item.data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=item.name,
        )
    return msg.as_bytes()


def forward_body_html(
    note_html: str | None,
    *,
    from_address: str,
    sent_at: datetime,
    subject: str,
    to: Sequence[str],
    original_html: str,
) -> str:
    """Telegram-style HTML of a forward: optional note, quote headers, original."""
    escape = html_lib.escape
    header_lines = [
        "---------- Forwarded message ----------",
        f"From: {escape(from_address)}",
        f"Date: {escape(format_datetime(sent_at))}",
        f"Subject: {escape(subject)}",
        f"To: {escape(', '.join(to))}",
    ]
    note = f"{note_html}\n\n" if note_html and note_html.strip() else ""
    return f"{note}{chr(10).join(header_lines)}\n\n{original_html}"
