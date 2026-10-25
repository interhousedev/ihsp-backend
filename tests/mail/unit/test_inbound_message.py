"""MAIL-2, MAIL-9: parsing raw messages."""

from app.modules.mail.domain.inbound_message import (
    body_is_empty,
    parse_headers,
    parse_message,
)
from tests.mail.helpers import PDF_BYTES, fixture_bytes, make_raw


def test_headers_of_a_plain_message_are_read() -> None:
    """MAIL-2: Message-ID, From, To and Subject."""
    headers = parse_headers(fixture_bytes("plain.eml"))

    assert headers.message_id == "<plain-1@example.com>"
    assert headers.from_address == "anna@example.com"
    assert headers.to == ("aleksey.brastilov@mail.ihsu.uz",)
    assert headers.subject == "Meeting tomorrow"
    assert headers.in_reply_to is None
    assert headers.date is not None


def test_threading_headers_and_cc_are_read() -> None:
    """MAIL-4: In-Reply-To and References keep the thread."""
    raw = make_raw(
        extra_headers={
            "In-Reply-To": "<a@example.com>",
            "References": "<x@example.com> <a@example.com>",
            "Cc": "Bob <bob@example.org>, carol@example.org",
            "Reply-To": "Lists <list@example.net>",
        }
    )

    headers = parse_headers(raw)

    assert headers.in_reply_to == "<a@example.com>"
    assert headers.references == ("<x@example.com>", "<a@example.com>")
    assert headers.cc == ("bob@example.org", "carol@example.org")
    assert headers.reply_to == "list@example.net"


def test_an_encoded_subject_is_decoded() -> None:
    """MAIL-2: RFC 2047 subjects."""
    raw = make_raw(subject="Заявка на справку")

    assert parse_headers(raw).subject == "Заявка на справку"


def test_a_message_without_message_id_has_none() -> None:
    """MAIL-9: the spam score needs to know."""
    assert parse_headers(make_raw(message_id=None)).message_id is None


def test_garbage_does_not_raise() -> None:
    """MAIL-9: malformed input gives empty headers, not an exception."""
    headers = parse_headers(b"\x00\xffnot a mail at all")
    parsed = parse_message(b"\x00\xffnot a mail at all")

    assert headers.from_address == ""
    assert parsed.attachments == ()


def test_empty_body_detection() -> None:
    """MAIL-9: whitespace after the header block counts as empty."""
    assert body_is_empty(b"Subject: x\r\n\r\n  \r\n")
    assert body_is_empty(b"Subject: x")
    assert not body_is_empty(b"Subject: x\r\n\r\nhi")


def test_a_plain_message_has_a_text_body_only() -> None:
    """MAIL-2: text/plain -> text, no html."""
    parsed = parse_message(fixture_bytes("plain.eml"))

    assert parsed.text is not None and "See you tomorrow" in parsed.text
    assert parsed.html is None
    assert parsed.attachments == ()
    assert parsed.report is None


def test_an_html_message_has_both_bodies_and_no_inline_image_attachment() -> None:
    """MAIL-2: the CID logo is part of the body, not an attachment."""
    parsed = parse_message(fixture_bytes("html_image_link.eml"))

    assert parsed.html is not None and "<b>Aleksey</b>" in parsed.html
    assert parsed.text is not None
    assert parsed.attachments == ()


def test_attachments_are_extracted_with_names_types_and_bytes() -> None:
    """MAIL-2: the PDF and the exe."""
    parsed = parse_message(fixture_bytes("pdf_and_exe.eml"))

    assert [(a.name, a.content_type) for a in parsed.attachments] == [
        ("report.pdf", "application/pdf"),
        ("setup.exe", "application/octet-stream"),
    ]
    assert parsed.attachments[0].data.startswith(b"%PDF")


def test_attachment_names_are_stripped_of_paths_and_control_characters() -> None:
    """MAIL-2: file names are untrusted."""
    raw = make_raw(
        attachments=[("..\\..\\evil/../name\x07.pdf", "application/pdf", PDF_BYTES)]
    )

    parsed = parse_message(raw)

    assert parsed.attachments[0].name == "name.pdf"


def test_a_message_that_is_html_only_has_no_text_body() -> None:
    """MAIL-2: plain_text() falls back to the converted HTML."""
    raw = make_raw(html="<p>Only <b>html</b></p>", body=None)
    parsed = parse_message(raw)

    assert parsed.html is not None
    assert "Only html" in parsed.plain_text()


def test_a_delivery_status_notification_is_detected() -> None:
    """MAIL-6: multipart/report; report-type=delivery-status."""
    raw = fixture_bytes("dsn_bounce.eml").replace(
        b"@@ORIGINAL_ID@@", b"<orig-1@mail.ihsu.uz>"
    )

    report = parse_message(raw).report

    assert report is not None
    assert report.failed
    assert report.original_ids == ("<orig-1@mail.ihsu.uz>",)
    assert report.reason is not None and "550 5.1.1" in report.reason


def test_a_delayed_notice_is_not_a_failure() -> None:
    """MAIL-8: Action: delayed does not count as a bounce."""
    raw = (
        fixture_bytes("dsn_bounce.eml")
        .replace(b"@@ORIGINAL_ID@@", b"<orig-1@mail.ihsu.uz>")
        .replace(b"Action: failed", b"Action: delayed")
    )

    report = parse_message(raw).report

    assert report is not None
    assert not report.failed


def test_the_original_id_also_comes_from_in_reply_to() -> None:
    """MAIL-6: some servers only set In-Reply-To on the DSN."""
    raw = (
        fixture_bytes("dsn_bounce.eml")
        .replace(b"@@ORIGINAL_ID@@", b"<embedded@mail.ihsu.uz>")
        .replace(
            b"Message-ID: <dsn-1@relay.example.net>",
            b"Message-ID: <dsn-1@relay.example.net>\r\n"
            b"In-Reply-To: <replied@mail.ihsu.uz>",
        )
    )

    report = parse_message(raw).report

    assert report is not None
    assert report.original_ids == ("<embedded@mail.ihsu.uz>", "<replied@mail.ihsu.uz>")


def test_an_attached_message_is_extracted_as_an_eml_file() -> None:
    """MAIL-2: message/rfc822 attachments keep their bytes (skipped later by type)."""
    raw = (
        b"From: anna@example.com\r\nTo: aleksey.brastilov@mail.ihsu.uz\r\n"
        b"Subject: Fwd\r\nMessage-ID: <fw@example.com>\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="b1"\r\n\r\n'
        b"--b1\r\nContent-Type: text/plain\r\n\r\nSee attached\r\n"
        b"--b1\r\nContent-Type: message/rfc822\r\n"
        b'Content-Disposition: attachment; filename="original.eml"\r\n\r\n'
        b"From: bob@example.org\r\nSubject: Inner\r\n\r\ninner body\r\n"
        b"--b1\r\nContent-Type: image/png\r\nContent-Disposition: attachment\r\n\r\n"
        b"\x89PNG\r\n--b1--\r\n"
    )

    parsed = parse_message(raw)

    names = [a.name for a in parsed.attachments]
    assert names == ["original.eml", "attachment-2.png"]
    assert b"Subject: Inner" in parsed.attachments[0].data


def test_an_unknown_charset_still_gives_text() -> None:
    """MAIL-2: broken declarations do not lose the body."""
    raw = (
        b"From: anna@example.com\r\nSubject: x\r\nMessage-ID: <c@example.com>\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=x-no-such-charset\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\ncaf\xc3\xa9 au lait\r\n"
    )

    parsed = parse_message(raw)

    assert parsed.text is not None and "au lait" in parsed.text


def test_a_broken_date_header_is_ignored() -> None:
    """MAIL-2: no exception, no date."""
    raw = make_raw().replace(b"Date:", b"Date: not a date\r\nX-Old-Date:")

    assert parse_headers(raw).date is None


def test_a_delivery_report_with_only_attached_headers_still_finds_the_original() -> (
    None
):
    """MAIL-6: text/rfc822-headers instead of message/rfc822."""
    raw = (
        fixture_bytes("dsn_bounce.eml")
        .replace(b"Content-Type: message/rfc822", b"Content-Type: text/rfc822-headers")
        .replace(b"@@ORIGINAL_ID@@", b"<only-headers@mail.ihsu.uz>")
    )

    report = parse_message(raw).report

    assert report is not None
    assert report.original_ids == ("<only-headers@mail.ihsu.uz>",)


def test_original_message_id_in_the_status_block_comes_first() -> None:
    """MAIL-6: Original-Message-ID (non-standard but common) is trusted first."""
    raw = (
        fixture_bytes("dsn_bounce.eml")
        .replace(
            b"Action: failed",
            b"Action: failed\r\nOriginal-Message-ID: <status@mail.ihsu.uz>",
        )
        .replace(b"@@ORIGINAL_ID@@", b"<embedded@mail.ihsu.uz>")
    )

    report = parse_message(raw).report

    assert report is not None
    assert report.original_ids[0] == "<status@mail.ihsu.uz>"
