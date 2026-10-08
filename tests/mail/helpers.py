"""Builders and loaders for mail tests."""

from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.shared.ids import new_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mail"
MAIL_DOMAIN = "mail.ihsu.uz"
LOGIN = "aleksey.brastilov"
ADDRESS = f"{LOGIN}@{MAIL_DOMAIN}"
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def fixture_bytes(name: str) -> bytes:
    """Read a fixture message from tests/fixtures/mail."""
    return (FIXTURES / name).read_bytes()


def make_raw(
    *,
    subject: str = "Hello",
    body: str | None = "Hello!",
    sender: str = "Anna Petrova <anna@example.com>",
    to: str = ADDRESS,
    message_id: str | None = "<m-1@example.com>",
    html: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    """Build a message; each attachment is (filename, "type/subtype", bytes)."""
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime(2026, 10, 6, 8, 30, tzinfo=UTC))
    if message_id is not None:
        msg["Message-ID"] = message_id
    for name, value in (extra_headers or {}).items():
        msg[name] = value
    if html is not None and body is None:
        msg.set_content(html, subtype="html")
    elif html is not None:
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body or "")
    for filename, content_type, data in attachments or []:
        maintype, _, subtype = content_type.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def make_mail(
    user_id: UUID,
    *,
    message_id: str = "<m-1@example.com>",
    direction: MailDirection = MailDirection.IN,
    status: MailStatus = MailStatus.RECEIVED,
    occurred_at: datetime | None = None,
    **changes: Any,
) -> MailMessage:
    """A mail row with sensible defaults; keyword arguments replace fields."""
    fields: dict[str, Any] = {
        "id": new_id(),
        "user_id": user_id,
        "direction": direction,
        "message_id": message_id,
        "from_address": "anna@example.com",
        "occurred_at": occurred_at or datetime(2026, 10, 6, 9, 0, tzinfo=UTC),
        "status": status,
        "to": [ADDRESS],
        "subject": "Subject",
        "snippet": "Snippet",
    }
    return MailMessage(**{**fields, **changes})
