"""MAIL-4, MAIL-6, MAIL-8: sending, replying and forwarding."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from uuid import UUID

from app.modules.mail.domain.errors import (
    InvalidRecipientError,
    MailboxUnavailableError,
    MailDailyLimitError,
    MailGlobalLimitError,
    MailNotFoundError,
    MailPurgedError,
    MailSuspendedError,
    MailTooLargeError,
    NoRecipientsError,
    TooManyRecipientsError,
)
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.shared.contracts.identity import UserRef, UserStatus
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.mail.helpers import PDF_BYTES, fixture_bytes, make_raw
from tests.mail.world import MailWorld, build_world

import pytest
from redis.asyncio import Redis


def raw_of(world: MailWorld, mail: MailMessage) -> EmailMessage:
    """Parse the stored raw file of a mail."""
    assert mail.raw_file_id is not None
    msg = BytesParser(policy=policy.default).parsebytes(
        world.files.blobs[mail.raw_file_id]
    )
    assert isinstance(msg, EmailMessage)
    return msg


async def test_a_sent_mail_is_queued_with_its_raw_message(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4, MAIL-6: row `queued`, raw stored for 30 days, delivery task started."""
    mail = await world.send_mail.execute(
        student.id,
        to=["teacher@example.org"],
        subject=" Question ",
        html="Hello <b>teacher</b>",
    )

    row = world.store.rows[mail.id]
    assert (row.direction, row.status) == (MailDirection.OUT, MailStatus.QUEUED)
    assert row.from_address == "aleksey.brastilov@mail.ihsu.uz"
    assert row.to == ["teacher@example.org"]
    assert row.subject == "Question"
    assert row.snippet == "Hello teacher"
    assert row.message_id == f"<{mail.id.hex}@mail.ihsu.uz>"
    assert row.occurred_at == world.clock.now()
    assert row.raw_file_id is not None
    assert world.files.expires[row.raw_file_id] == 30
    assert world.kicker.calls == [("mail.send_outbound", {"mail_id": mail.id})]


async def test_the_message_is_sent_from_the_students_mailbox_with_a_name(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: From: "First Last" <login@domain>, HTML plus plain text."""
    mail = await world.send_mail.execute(
        student.id, to=["teacher@example.org"], subject="Question", html="Hi\nthere"
    )

    msg = raw_of(world, world.store.rows[mail.id])

    assert msg["From"].addresses[0].display_name == "Aleksey Brastilov"
    assert msg["From"].addresses[0].addr_spec == "aleksey.brastilov@mail.ihsu.uz"
    assert msg["Message-ID"] == world.store.rows[mail.id].message_id
    assert msg["In-Reply-To"] is None
    assert msg.get_body(preferencelist=("plain",)) is not None
    html = msg.get_body(preferencelist=("html",))
    assert html is not None and "Hi<br>" in html.get_content()


async def test_recipients_are_validated_and_deduplicated(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: email-validator; duplicates collapse; names are normalized."""
    mail = await world.send_mail.execute(
        student.id,
        to=[" Teacher@Example.ORG ", "teacher@example.org", "other@example.org"],
        subject="x",
        html="x",
    )

    assert world.store.rows[mail.id].to == ["Teacher@example.org", "other@example.org"]


@pytest.mark.parametrize(
    "bad", ["not-an-address", "a@b", "two words@example.org", "a@@example.org"]
)
async def test_an_invalid_recipient_is_refused(
    world: MailWorld, student: UserRef, bad: str
) -> None:
    """UF-MAIL-03 1a: invalid address -> asked again."""
    with pytest.raises(InvalidRecipientError) as raised:
        await world.send_mail.execute(student.id, to=[bad], subject="x", html="x")

    assert raised.value.params == {"address": bad}
    assert world.store.rows == {}


async def test_no_recipients_is_refused(world: MailWorld, student: UserRef) -> None:
    """MAIL-6: at least one recipient."""
    with pytest.raises(NoRecipientsError):
        await world.send_mail.execute(student.id, to=["  "], subject="x", html="x")


async def test_more_than_five_recipients_are_refused(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: 5 recipients per email."""
    five = [f"user{i}@example.org" for i in range(5)]
    await world.send_mail.execute(student.id, to=five, subject="x", html="x")

    with pytest.raises(TooManyRecipientsError) as raised:
        await world.send_mail.execute(
            student.id, to=[*five, "user5@example.org"], subject="x", html="x"
        )

    assert raised.value.params == {"limit": 5}


async def test_a_suspended_mailbox_cannot_send(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: suspended -> refused, nothing stored, receiving is unaffected."""
    world.suspension.reasons[student.id] = "abuse"

    with pytest.raises(MailSuspendedError):
        await world.send_mail.execute(
            student.id, to=["a@example.org"], subject="x", html="x"
        )

    assert world.store.rows == {} and world.files.refs == {}
    assert await world.deliver(fixture_bytes("plain.eml"))


async def test_the_daily_limit_is_per_student_and_resets_the_next_day(
    redis: Redis, clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """MAIL-6: 20 emails per day (limit lowered to 3 here)."""
    world = build_world(clock, kicker, redis, per_day_limit=3)
    first = world.student("first.student")
    second = world.student("second.student")
    for _ in range(3):
        await world.send_mail.execute(
            first.id, to=["a@example.org"], subject="x", html="x"
        )

    with pytest.raises(MailDailyLimitError) as raised:
        await world.send_mail.execute(
            first.id, to=["a@example.org"], subject="x", html="x"
        )
    await world.send_mail.execute(
        second.id, to=["a@example.org"], subject="x", html="x"
    )
    clock.advance(days=1)
    await world.send_mail.execute(first.id, to=["a@example.org"], subject="x", html="x")

    assert raised.value.params == {"limit": 3}
    assert len(world.store.rows) == 5


async def test_the_global_daily_cap_applies_to_everybody(
    redis: Redis, clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """MAIL-6: a global daily cap (lowered to 2 here)."""
    world = build_world(clock, kicker, redis, global_per_day_limit=2)
    users = [world.student(f"student.{i}") for i in range(3)]
    for user in users[:2]:
        await world.send_mail.execute(
            user.id, to=["a@example.org"], subject="x", html="x"
        )

    with pytest.raises(MailGlobalLimitError):
        await world.send_mail.execute(
            users[2].id, to=["a@example.org"], subject="x", html="x"
        )


async def test_a_refused_mail_does_not_use_up_the_daily_limit(
    redis: Redis, clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """MAIL-6: validation happens before the counters are touched."""
    world = build_world(clock, kicker, redis, per_day_limit=1)
    user = world.student()
    with pytest.raises(InvalidRecipientError):
        await world.send_mail.execute(user.id, to=["bad"], subject="x", html="x")

    await world.send_mail.execute(user.id, to=["a@example.org"], subject="x", html="x")


@pytest.mark.parametrize(
    "status",
    [UserStatus.BLOCKED, UserStatus.DEACTIVATED, UserStatus.PENDING_ACTIVATION],
)
async def test_users_without_an_active_mailbox_cannot_send(
    world: MailWorld, status: UserStatus
) -> None:
    """MAIL-1: only active students with a login have a mailbox."""
    user = world.student("some.login", status=status)

    with pytest.raises(MailboxUnavailableError):
        await world.send_mail.execute(
            user.id, to=["a@example.org"], subject="x", html="x"
        )


async def test_a_message_that_is_too_large_is_refused(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: the relay's size limit (25 MB)."""
    huge = "x" * (26 * 1024 * 1024)

    with pytest.raises(MailTooLargeError):
        await world.send_mail.execute(
            student.id, to=["a@example.org"], subject="x", html=huge
        )

    assert world.files.refs == {}


# - - - Reply - - -


async def _received(world: MailWorld, **kwargs: object) -> UUID:
    return await world.deliver_and_parse(make_raw(**kwargs))  # type: ignore[arg-type]


async def test_a_reply_keeps_the_thread(world: MailWorld, student: UserRef) -> None:
    """MAIL-4: In-Reply-To = original Message-ID; References = its references + it."""
    original = await _received(
        world,
        subject="Question",
        message_id="<orig@example.com>",
        extra_headers={"References": "<root@example.com>"},
    )

    reply = await world.reply_mail.execute(student.id, original, html="Thanks")

    msg = raw_of(world, world.store.rows[reply.id])
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<root@example.com> <orig@example.com>"
    assert msg["Subject"] == "Re: Question"
    assert str(msg["To"]) == "anna@example.com"
    assert world.store.rows[reply.id].in_reply_to == "<orig@example.com>"
    assert world.store.rows[reply.id].references == [
        "<root@example.com>",
        "<orig@example.com>",
    ]


async def test_a_reply_goes_to_reply_to_when_the_mail_has_one(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: mailing lists set Reply-To."""
    original = await _received(world, extra_headers={"Reply-To": "list@example.net"})

    reply = await world.reply_mail.execute(student.id, original, html="Thanks")

    assert world.store.rows[reply.id].to == ["list@example.net"]


async def test_a_reply_works_after_the_raw_mail_was_deleted(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: headers stay in the row, so threading still works."""
    original = await _received(world, message_id="<orig@example.com>")
    raw_file = world.store.rows[original].raw_file_id
    assert raw_file is not None
    world.files.delete(raw_file)

    reply = await world.reply_mail.execute(student.id, original, html="Thanks")

    assert world.store.rows[reply.id].to == ["anna@example.com"]
    assert world.store.rows[reply.id].in_reply_to == "<orig@example.com>"


async def test_re_is_not_repeated(world: MailWorld, student: UserRef) -> None:
    """MAIL-4: Re: Re: ... is avoided."""
    original = await _received(world, subject="Re: Question")

    reply = await world.reply_mail.execute(student.id, original, html="x")

    assert world.store.rows[reply.id].subject == "Re: Question"


async def test_replying_to_a_sent_mail_goes_to_its_recipients(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: a follow-up in the same thread."""
    sent = await world.send_mail.execute(
        student.id, to=["teacher@example.org"], subject="Question", html="x"
    )

    reply = await world.reply_mail.execute(student.id, sent.id, html="One more thing")

    assert world.store.rows[reply.id].to == ["teacher@example.org"]
    assert world.store.rows[reply.id].in_reply_to == sent.message_id


async def test_another_students_mail_cannot_be_replied_to(world: MailWorld) -> None:
    """MAIL-4: mailboxes are private."""
    owner = world.student("owner.one")
    intruder = world.student("intruder.two")
    original = await world.deliver_and_parse(
        make_raw(to="owner.one@mail.ihsu.uz"),
        recipients=["owner.one@mail.ihsu.uz"],
    )

    with pytest.raises(MailNotFoundError):
        await world.reply_mail.execute(intruder.id, original, html="x")
    assert owner.id != intruder.id


# - - - Forward - - -


async def test_a_forward_quotes_the_original_and_attaches_its_files(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2, MAIL-4: quoted headers, original body, original attachments."""
    original = await world.deliver_and_parse(fixture_bytes("pdf_and_exe.eml"))

    forward = await world.forward_mail.execute(
        student.id,
        original,
        to=["friend@example.org"],
        note_html="FYI <b>please read</b>",
    )

    msg = raw_of(world, world.store.rows[forward.id])
    assert msg["Subject"] == "Fwd: Report and installer"
    assert str(msg["To"]) == "friend@example.org"
    assert msg["In-Reply-To"] is None
    body = msg.get_body(preferencelist=("plain",))
    assert body is not None
    text = body.get_content()
    assert text.startswith("FYI please read")
    assert "Forwarded message" in text
    assert "From: anna@example.com" in text
    assert "Subject: Report and installer" in text
    assert "The report is attached" in text
    assert [a.get_filename() for a in msg.iter_attachments()] == ["report.pdf"]


async def test_a_forward_without_a_note_starts_with_the_quote(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: the note is optional."""
    original = await _received(world)

    forward = await world.forward_mail.execute(
        student.id, original, to=["friend@example.org"], note_html=None
    )

    body = raw_of(world, world.store.rows[forward.id]).get_body(
        preferencelist=("plain",)
    )
    assert body is not None
    assert body.get_content().startswith("---------- Forwarded message")


async def test_a_mail_whose_raw_file_is_gone_cannot_be_forwarded(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: only the headers are left after 30 days."""
    original = await _received(world)
    raw_file = world.store.rows[original].raw_file_id
    assert raw_file is not None
    world.files.delete(raw_file)

    with pytest.raises(MailPurgedError):
        await world.forward_mail.execute(
            student.id, original, to=["friend@example.org"], note_html=None
        )


async def test_forward_recipients_are_limited_like_new_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: the same rules apply."""
    original = await _received(world)

    with pytest.raises(TooManyRecipientsError):
        await world.forward_mail.execute(
            student.id,
            original,
            to=[f"u{i}@example.org" for i in range(6)],
            note_html=None,
        )


async def test_a_pdf_attachment_bytes_survive_the_forward(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: the forwarded file equals the stored one."""
    original = await world.deliver_and_parse(
        make_raw(attachments=[("a.pdf", "application/pdf", PDF_BYTES)])
    )

    forward = await world.forward_mail.execute(
        student.id, original, to=["friend@example.org"], note_html=None
    )

    attachment = next(raw_of(world, world.store.rows[forward.id]).iter_attachments())
    assert attachment.get_content() == PDF_BYTES


async def test_forwarding_a_plain_text_mail_quotes_the_escaped_text(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: no HTML body -> the text body is quoted, escaped."""
    original = await _received(world, body="1 < 2 & 3")

    forward = await world.forward_mail.execute(
        student.id, original, to=["friend@example.org"], note_html=None
    )

    body = raw_of(world, world.store.rows[forward.id]).get_body(
        preferencelist=("plain",)
    )
    assert body is not None
    assert "1 < 2 & 3" in body.get_content()


async def test_a_deleted_attachment_is_left_out_of_a_forward(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: attachments expire with the raw mail."""
    original = await world.deliver_and_parse(
        make_raw(attachments=[("a.pdf", "application/pdf", PDF_BYTES)])
    )
    world.files.delete(world.store.rows[original].attachment_file_ids[0])

    forward = await world.forward_mail.execute(
        student.id, original, to=["friend@example.org"], note_html=None
    )

    assert list(raw_of(world, world.store.rows[forward.id]).iter_attachments()) == []


async def test_a_reply_to_a_mail_without_a_raw_file_uses_the_stored_sender(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: the row alone is enough to answer."""
    original = await _received(world)
    world.store.rows[original].raw_file_id = None

    reply = await world.reply_mail.execute(student.id, original, html="Thanks")

    assert world.store.rows[reply.id].to == ["anna@example.com"]
