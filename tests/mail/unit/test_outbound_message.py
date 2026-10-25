"""MAIL-4, MAIL-6: building outbound messages."""

from dataclasses import replace
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Any
from uuid import UUID

from app.modules.mail.domain.inbound_message import Attachment
from app.modules.mail.domain.outbound_message import (
    OutboundDraft,
    build_message,
    forward_subject,
    new_message_id,
    reply_subject,
    thread_references,
)
from tests.mail.helpers import PDF_BYTES


def draft(**changes: Any) -> OutboundDraft:
    """A valid draft; keyword arguments replace fields."""
    base = OutboundDraft(
        display_name="Aleksey Brastilov",
        login="aleksey.brastilov",
        domain="mail.ihsu.uz",
        to=["teacher@example.org"],
        subject="Question",
        html="Hello <b>teacher</b>\nSecond line",
        message_id="<id-1@mail.ihsu.uz>",
        sent_at=datetime(2026, 10, 6, 9, 0, tzinfo=UTC),
    )
    return replace(base, **changes)


def parse(raw: bytes) -> EmailMessage:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert isinstance(msg, EmailMessage)
    return msg


def test_headers_are_set() -> None:
    """MAIL-4: From has the display name and the mailbox address."""
    msg = parse(build_message(draft()))

    assert msg["From"].addresses[0].display_name == "Aleksey Brastilov"
    assert msg["From"].addresses[0].addr_spec == "aleksey.brastilov@mail.ihsu.uz"
    assert str(msg["To"]) == "teacher@example.org"
    assert msg["Subject"] == "Question"
    assert msg["Message-ID"] == "<id-1@mail.ihsu.uz>"
    assert msg["Date"] is not None
    assert msg["In-Reply-To"] is None


def test_the_body_has_html_and_a_plain_alternative() -> None:
    """MAIL-4: HTML body plus plain text generated from it."""
    msg = parse(build_message(draft()))

    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    assert plain is not None and html is not None
    assert plain.get_content().strip().splitlines() == ["Hello teacher", "Second line"]
    assert "<b>teacher</b><br>" in html.get_content()


def test_scripts_in_the_body_are_removed() -> None:
    """MAIL-4: the bot's HTML is sanitized."""
    msg = parse(build_message(draft(html="hi<script>evil()</script>")))

    html = msg.get_body(preferencelist=("html",))
    assert html is not None
    assert "script" not in html.get_content()


def test_reply_headers_keep_the_thread() -> None:
    """MAIL-4: In-Reply-To and References."""
    msg = parse(
        build_message(
            draft(
                in_reply_to="<orig@example.org>",
                references=["<root@example.org>", "<orig@example.org>"],
            )
        )
    )

    assert msg["In-Reply-To"] == "<orig@example.org>"
    assert msg["References"] == "<root@example.org> <orig@example.org>"


def test_attachments_are_attached_with_names() -> None:
    """MAIL-2: a forward carries the original attachments."""
    msg = parse(
        build_message(
            draft(attachments=[Attachment("report.pdf", "application/pdf", PDF_BYTES)])
        )
    )

    attachments = list(msg.iter_attachments())
    assert [a.get_filename() for a in attachments] == ["report.pdf"]
    assert attachments[0].get_content() == PDF_BYTES


def test_non_ascii_names_and_subjects_survive() -> None:
    """MAIL-4: Cyrillic display names and subjects are encoded."""
    raw = build_message(
        draft(display_name="Алексей Брастилов", subject="Вопрос по курсу")
    )

    msg = parse(raw)

    assert msg["From"].addresses[0].display_name == "Алексей Брастилов"
    assert msg["Subject"] == "Вопрос по курсу"
    assert raw.isascii()


def test_the_message_id_uses_the_mail_domain() -> None:
    """MAIL-6: Message-ID in the mail domain."""
    mail_id = UUID("01930000-0000-7000-8000-000000000001")

    assert new_message_id(mail_id, "mail.ihsu.uz") == f"<{mail_id.hex}@mail.ihsu.uz>"


def test_subject_prefixes_are_not_doubled() -> None:
    """MAIL-4: Re: and Fwd:."""
    assert reply_subject("Question") == "Re: Question"
    assert reply_subject("Re: Question") == "Re: Question"
    assert forward_subject("Question") == "Fwd: Question"
    assert forward_subject("Fwd: Question") == "Fwd: Question"


def test_references_grow_with_the_original_id_and_stay_bounded() -> None:
    """MAIL-4: References = original references + its Message-ID, at most 20."""
    old = [f"<{i}@example.org>" for i in range(30)]

    refs = thread_references(old, "<last@example.org>")

    assert refs[-1] == "<last@example.org>"
    assert len(refs) == 20
