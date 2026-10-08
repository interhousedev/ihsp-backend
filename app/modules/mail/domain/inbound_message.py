"""Parsing of raw RFC 5322 messages with the standard library (MAIL-2, MAIL-9)."""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.parser import BytesHeaderParser, HeaderParser
from typing import Any

from app.modules.mail.domain.telegram_html import html_to_text

_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")
_HEADER_END_RE = re.compile(rb"\r?\n\r?\n")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_NOT_ATTACHMENTS = frozenset({"message/delivery-status", "text/rfc822-headers"})
_ATOMIC = frozenset({"message/rfc822", "message/delivery-status"})
MAX_NAME_LENGTH = 150
MAX_HEADER_BYTES = 65536
MAX_FIELD = {"message_id": 998, "address": 320}


@dataclass(frozen=True, slots=True)
class MailHeaders:
    """The headers the mailbox keeps (and the spam checks look at)."""

    message_id: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    from_address: str
    reply_to: str | None
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    date: datetime | None


@dataclass(frozen=True, slots=True)
class Attachment:
    """A file inside a message."""

    name: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """What a delivery status notification (DSN) says about an earlier mail."""

    original_ids: tuple[str, ...]
    failed: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class ParsedMail:
    """A message split into headers, bodies, attachments and a DSN report."""

    headers: MailHeaders
    html: str | None
    text: str | None
    attachments: tuple[Attachment, ...]
    report: DeliveryReport | None

    def plain_text(self) -> str:
        """The text body, or the HTML body converted to text, or ''."""
        if self.text:
            return self.text
        return html_to_text(self.html) if self.html else ""


# - - - Headers - - -


def _header_text(msg: Message[Any, Any], name: str) -> str:
    try:
        value = msg[name]
        return "" if value is None else " ".join(str(value).split())
    except (LookupError, ValueError, AttributeError):
        return ""


def _first_message_id(value: str) -> str | None:
    found = _MESSAGE_ID_RE.search(value)
    if found:
        return found.group(0)[: MAX_FIELD["message_id"]]
    return value[: MAX_FIELD["message_id"]] or None


def _addresses(msg: Message[Any, Any], name: str) -> tuple[str, ...]:
    found: list[str] = []
    try:
        for header in msg.get_all(name, []):
            for address in getattr(header, "addresses", ()):
                if address.addr_spec:
                    found.append(address.addr_spec[: MAX_FIELD["address"]])
    except (LookupError, ValueError, AttributeError):
        return tuple(found)
    return tuple(found)


def _date(msg: Message[Any, Any]) -> datetime | None:
    try:
        value = msg["Date"]
        parsed = None if value is None else value.datetime
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, datetime) else None


def read_headers(msg: Message[Any, Any]) -> MailHeaders:
    """Extract the stored headers; broken headers become empty values."""
    from_list = _addresses(msg, "From")
    reply_list = _addresses(msg, "Reply-To")
    return MailHeaders(
        message_id=_first_message_id(_header_text(msg, "Message-ID")),
        in_reply_to=_first_message_id(_header_text(msg, "In-Reply-To")),
        references=tuple(_MESSAGE_ID_RE.findall(_header_text(msg, "References"))),
        from_address=from_list[0] if from_list else "",
        reply_to=reply_list[0] if reply_list else None,
        to=_addresses(msg, "To"),
        cc=_addresses(msg, "Cc"),
        subject=_header_text(msg, "Subject"),
        date=_date(msg),
    )


def parse_headers(raw: bytes) -> MailHeaders:
    """Read only the header block (cheap; used while the SMTP client waits)."""
    end = _HEADER_END_RE.search(raw)
    head = raw[: end.end()] if end else raw[:MAX_HEADER_BYTES]
    msg = BytesHeaderParser(policy=policy.default).parsebytes(head)
    return read_headers(msg)


def body_is_empty(raw: bytes) -> bool:
    """True when nothing but whitespace follows the header block."""
    end = _HEADER_END_RE.search(raw)
    return end is None or not raw[end.end() :].strip()


# - - - Bodies and attachments - - -


def _text_of(part: EmailMessage) -> str:
    try:
        text = str(part.get_content())
    except (LookupError, UnicodeError):
        payload = part.get_payload(decode=True)
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _body(msg: EmailMessage, kind: str) -> str | None:
    part = msg.get_body(preferencelist=(kind,))
    if part is None or not isinstance(part, EmailMessage):
        return None
    text = _text_of(part)
    return text if text.strip() else None


def _is_attachment(part: Message[Any, Any]) -> bool:
    content_type = part.get_content_type()
    if content_type in _NOT_ATTACHMENTS:
        return False
    if part.get_content_disposition() == "attachment":
        return True
    # Inline images referenced by Content-ID are part of the body, not attachments.
    return bool(part.get_filename()) and part["Content-ID"] is None


def _clean_name(name: str | None, content_type: str, number: int) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = _CONTROL_RE.sub("", base).strip()[:MAX_NAME_LENGTH]
    if base:
        return base
    extension = mimetypes.guess_extension(content_type) or ".bin"
    if content_type == "message/rfc822":
        extension = ".eml"
    return f"attachment-{number}{extension}"


def _part_bytes(part: Message[Any, Any]) -> bytes:
    if part.get_content_type() == "message/rfc822":
        inner: Any = part.get_payload()
        if isinstance(inner, list) and inner:
            return bytes(inner[0].as_bytes())
        return b""
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _leaves(part: EmailMessage) -> Iterator[EmailMessage]:
    """Yield the leaf parts; an attached message is one unit, not opened."""
    if part.get_content_type() in _ATOMIC or not part.is_multipart():
        yield part
        return
    for child in part.iter_parts():
        if isinstance(child, EmailMessage):
            yield from _leaves(child)


def _attachments(msg: EmailMessage) -> tuple[Attachment, ...]:
    found: list[Attachment] = []
    for part in _leaves(msg):
        if not _is_attachment(part):
            continue
        content_type = part.get_content_type()
        name = _clean_name(part.get_filename(), content_type, len(found) + 1)
        found.append(Attachment(name, content_type, _part_bytes(part)))
    return tuple(found)


# - - - Delivery status notifications - - -


def _group_value(groups: list[Message[Any, Any]], name: str) -> list[str]:
    return [str(g[name]).strip() for g in groups if g[name] is not None]


def _embedded_ids(msg: EmailMessage) -> list[str]:
    found: list[str] = []
    for part in msg.walk():
        content_type = part.get_content_type()
        inner: Any = None
        if content_type == "message/rfc822":
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else None
        elif content_type == "text/rfc822-headers":
            text = part.get_payload(decode=True)
            if isinstance(text, bytes):
                inner = HeaderParser().parsestr(text.decode("utf-8", "replace"))
        value = None if inner is None else inner["Message-ID"]
        if value:
            found.extend(_MESSAGE_ID_RE.findall(str(value)))
    return found


def _report(msg: EmailMessage, headers: MailHeaders) -> DeliveryReport | None:
    is_report = msg.get_content_type() == "multipart/report"
    if not is_report or str(msg.get_param("report-type")).lower() != "delivery-status":
        return None
    groups: list[Message[Any, Any]] = []
    for part in msg.walk():
        payload: Any = part.get_payload()
        if part.get_content_type() == "message/delivery-status" and isinstance(
            payload, list
        ):
            groups.extend(payload)
    original = [
        found
        for value in _group_value(groups, "Original-Message-ID")
        for found in _MESSAGE_ID_RE.findall(value)
    ]
    ids = [*original, *_embedded_ids(msg)]
    if headers.in_reply_to:
        ids.append(headers.in_reply_to)
    ids.extend(reversed(headers.references))
    actions = [a.lower() for a in _group_value(groups, "Action")]
    reasons = _group_value(groups, "Diagnostic-Code") or _group_value(groups, "Status")
    return DeliveryReport(
        original_ids=tuple(dict.fromkeys(ids)),
        failed=not actions or "failed" in actions,
        reason=reasons[0][:300] if reasons else None,
    )


def parse_message(raw: bytes) -> ParsedMail:
    """Parse a stored message; never raises for malformed input."""
    msg = message_from_bytes(raw, policy=policy.default)
    if not isinstance(msg, EmailMessage):
        msg = EmailMessage()
    headers = read_headers(msg)
    return ParsedMail(
        headers=headers,
        html=_body(msg, "html"),
        text=_body(msg, "plain"),
        attachments=_attachments(msg),
        report=_report(msg, headers),
    )
