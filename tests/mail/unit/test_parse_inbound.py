"""MAIL-2, MAIL-5, MAIL-6: parsing a received mail and notifying the student."""

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.mail_status import MailStatus
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.files import FileScope
from app.shared.contracts.identity import UserRef
from app.shared.notifications import NotificationType
from tests.mail.helpers import PDF_BYTES, fixture_bytes, make_raw
from tests.mail.world import MailWorld

import pytest


async def test_the_snippet_is_the_first_200_characters_of_the_text(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: snippet for lists and button labels."""
    raw = make_raw(body="word " * 100)

    mail_id = await world.deliver_and_parse(raw)

    snippet = world.store.rows[mail_id].snippet
    assert len(snippet) == 200
    assert snippet.startswith("word word")


async def test_the_snippet_of_an_html_only_mail_comes_from_the_html(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: HTML converted to text."""
    raw = make_raw(html="<p>Only <b>html</b> here</p>", body=None)

    mail_id = await world.deliver_and_parse(raw)

    assert world.store.rows[mail_id].snippet == "Only html here"


async def test_a_received_mail_is_forwarded_to_telegram_once(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: a `mail` notification with the dedupe key mail:{id}."""
    mail_id = await world.deliver_and_parse(fixture_bytes("plain.eml"))

    assert [
        (n.user_id, n.type, n.payload, n.dedupe_key) for n in world.store.notifications
    ] == [
        (
            student.id,
            NotificationType.MAIL,
            {"mail_id": str(mail_id)},
            f"mail:{mail_id}",
        )
    ]


async def test_parsing_twice_notifies_once(world: MailWorld, student: UserRef) -> None:
    """MAIL-2: the sweep may run the task again."""
    mail_id = await world.deliver_and_parse(fixture_bytes("plain.eml"))
    first_parse = world.store.rows[mail_id].meta.parsed_at

    world.clock.advance(minutes=20)
    await world.parse_inbound.execute(mail_id)

    assert len(world.store.notifications) == 1
    assert world.store.rows[mail_id].meta.parsed_at == first_parse


async def test_spam_is_not_forwarded(world: MailWorld, student: UserRef) -> None:
    """MAIL-5: spam score >= 5 -> no notification."""
    world.authenticator.checks = InboundChecks(spf="fail")

    mail_id = await world.deliver_and_parse(make_raw(message_id=None))

    assert world.store.rows[mail_id].status == MailStatus.SPAM
    assert world.store.notifications == []
    assert world.store.rows[mail_id].meta.parsed_at is not None


async def test_forwarding_can_be_switched_off(world: MailWorld) -> None:
    """MAIL-2: preferences.mail_forward_to_telegram = false."""
    world.student(forward_to_telegram=False)

    await world.deliver_and_parse(fixture_bytes("plain.eml"))

    assert world.store.notifications == []


async def test_a_pdf_is_stored_and_an_exe_is_listed_by_name(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2, FILE-4: allowed attachments become files, others are skipped."""
    mail_id = await world.deliver_and_parse(fixture_bytes("pdf_and_exe.eml"))

    row = world.store.rows[mail_id]
    assert len(row.attachment_file_ids) == 1
    pdf = world.files.refs[row.attachment_file_ids[0]]
    assert pdf.name == "report.pdf"
    assert pdf.scope == FileScope.MAIL
    assert world.files.blobs[pdf.id].startswith(b"%PDF-1.4")
    assert world.files.expires[pdf.id] == 30
    assert row.meta.skipped_attachments == ["setup.exe"]
    assert [n.type for n in world.store.notifications] == [NotificationType.MAIL]


async def test_an_attachment_over_50_mb_is_skipped(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: attachments up to 50 MB."""
    big = b"%PDF" + b"0" * (50 * 1024 * 1024)
    raw = make_raw(attachments=[("big.pdf", "application/pdf", big)])

    mail_id = await world.deliver_and_parse(raw)

    row = world.store.rows[mail_id]
    assert row.attachment_file_ids == []
    assert row.meta.skipped_attachments == ["big.pdf"]


async def test_more_than_twenty_attachments_are_not_all_stored(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: the rest is listed as skipped."""
    attachments = [(f"a{i}.pdf", "application/pdf", PDF_BYTES) for i in range(23)]

    mail_id = await world.deliver_and_parse(make_raw(attachments=attachments))

    row = world.store.rows[mail_id]
    assert len(row.attachment_file_ids) == 20
    assert row.meta.skipped_attachments == ["a20.pdf", "a21.pdf", "a22.pdf"]


async def _sent_mail(world: MailWorld, student: UserRef) -> str:
    sent = await world.send_mail.execute(
        student.id,
        to=["nobody@example.org"],
        subject="Question about the course",
        html="Hello!",
    )
    return sent.message_id


async def test_a_bounce_marks_the_sent_mail_and_notifies_without_forwarding_the_dsn(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: DSN -> original `bounced`, `mail_bounced` notification, no `mail` one."""
    message_id = await _sent_mail(world, student)
    sent = next(r for r in world.store.all() if r.message_id == message_id)
    world.clock.advance(hours=2)
    dsn = fixture_bytes("dsn_bounce.eml").replace(
        b"@@ORIGINAL_ID@@", message_id.encode()
    )

    await world.deliver_and_parse(dsn)

    bounced = world.store.rows[sent.id]
    assert bounced.status == MailStatus.BOUNCED
    assert bounced.meta.bounced_at == world.clock.now()
    assert (
        bounced.meta.bounce_reason is not None
        and "550 5.1.1" in bounced.meta.bounce_reason
    )
    assert [(n.type, n.payload, n.dedupe_key) for n in world.store.notifications] == [
        (
            NotificationType.MAIL_BOUNCED,
            {"mail_id": str(sent.id), "to": ["nobody@example.org"]},
            f"mail-bounced:{sent.id}",
        )
    ]


async def test_a_bounce_for_an_unknown_mail_is_an_ordinary_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: nothing to match -> forwarded like any mail."""
    dsn = fixture_bytes("dsn_bounce.eml").replace(
        b"@@ORIGINAL_ID@@", b"<unknown@mail.ihsu.uz>"
    )

    await world.deliver_and_parse(dsn)

    assert [n.type for n in world.store.notifications] == [NotificationType.MAIL]


async def test_a_bounce_of_another_students_mail_is_not_matched(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: the match is limited to the mailbox that received the DSN."""
    other = world.student("maria.ivanova")
    sent = await world.send_mail.execute(
        other.id, to=["nobody@example.org"], subject="Hi", html="Hello"
    )
    dsn = fixture_bytes("dsn_bounce.eml").replace(
        b"@@ORIGINAL_ID@@", sent.message_id.encode()
    )

    await world.deliver_and_parse(dsn)

    assert world.store.rows[sent.id].status == MailStatus.QUEUED


async def test_a_missing_raw_file_marks_the_mail_parsed_without_failing(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: the raw file may be gone when the task finally runs."""
    created = await world.deliver(fixture_bytes("plain.eml"))
    row = world.store.rows[created[0]]
    assert row.raw_file_id is not None
    world.files.delete(row.raw_file_id)

    await world.parse_inbound.execute(created[0])

    assert world.store.rows[created[0]].meta.parsed_at is not None


async def test_parsing_an_unknown_or_sent_mail_does_nothing(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: only received mails are parsed."""
    sent = await world.send_mail.execute(
        student.id, to=["nobody@example.org"], subject="Hi", html="Hello"
    )

    await world.parse_inbound.execute(sent.id)

    assert world.store.rows[sent.id].meta.parsed_at is None


async def test_a_row_without_a_raw_file_is_marked_parsed(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: nothing to parse, nothing to retry."""
    [mail_id] = await world.deliver(fixture_bytes("plain.eml"))
    world.store.rows[mail_id].raw_file_id = None

    await world.parse_inbound.execute(mail_id)

    assert world.store.rows[mail_id].meta.parsed_at is not None
    assert world.store.notifications[0].dedupe_key == f"mail:{mail_id}"


async def test_an_attachment_that_cannot_be_stored_is_listed_as_skipped(
    world: MailWorld, student: UserRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAIL-2: a quota or storage error does not lose the mail."""

    async def refuse(**kwargs: object) -> None:
        raise ValidationFailedError()

    [mail_id] = await world.deliver(fixture_bytes("pdf_and_exe.eml"))
    monkeypatch.setattr(world.files, "store_bytes", refuse)

    await world.parse_inbound.execute(mail_id)

    row = world.store.rows[mail_id]
    assert row.attachment_file_ids == []
    assert row.meta.skipped_attachments == ["report.pdf", "setup.exe"]
    assert row.meta.parsed_at is not None
