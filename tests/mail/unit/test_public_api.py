"""MAIL-2, MAIL-3, MAIL-4: the MailApi used by the bot."""

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.errors import MailNotFoundError, NotAnInboundMailError
from app.modules.mail.domain.mail_status import MailStatus
from app.shared.contracts.identity import UserRef
from app.shared.notifications import NotificationType
from tests.mail.helpers import fixture_bytes, make_raw
from tests.mail.world import MailWorld

import pytest


async def _receive_numbered(world: MailWorld, count: int) -> list[str]:
    subjects = []
    for number in range(count):
        subject = f"Mail {number}"
        subjects.append(subject)
        await world.deliver_and_parse(
            make_raw(subject=subject, message_id=f"<n{number}@example.com>")
        )
        world.clock.advance(minutes=5)
    return subjects


async def test_recent_lists_the_newest_mails_first(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-3: the last 10 emails, newest first."""
    subjects = await _receive_numbered(world, 12)

    page = await world.public.recent(student.id, limit=10)

    assert [m.subject for m in page] == list(reversed(subjects))[:10]
    assert page[0].direction == "in"
    assert page[0].from_address == "anna@example.com"
    assert not page[0].purged


async def test_recent_pages_with_the_before_cursor(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-3: Older -> before = occurred_at of the last item."""
    subjects = await _receive_numbered(world, 12)
    first = await world.public.recent(student.id, limit=10)

    second = await world.public.recent(
        student.id, limit=10, before=first[-1].occurred_at
    )

    assert [m.subject for m in second] == list(reversed(subjects))[10:]


async def test_recent_includes_sent_mail_and_hides_spam(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-3, MAIL-5: both directions, no spam."""
    await world.deliver_and_parse(fixture_bytes("plain.eml"))
    world.authenticator.checks = InboundChecks(spf="fail")
    await world.deliver(make_raw(message_id=None))
    await world.public.send(student.id, to=["a@example.org"], subject="Sent", html="x")

    page = await world.public.recent(student.id)

    assert sorted((m.direction, m.subject) for m in page) == [
        ("in", "Meeting tomorrow"),
        ("out", "Sent"),
    ]


async def test_recent_shows_only_the_users_own_mail(world: MailWorld) -> None:
    """MAIL-3: mailboxes are private."""
    first = world.student("first.student")
    second = world.student("second.student")
    await world.deliver(
        fixture_bytes("plain.eml"), recipients=["first.student@mail.ihsu.uz"]
    )

    assert len(await world.public.recent(first.id)) == 1
    assert await world.public.recent(second.id) == []


async def test_a_purged_mail_is_marked_purged_in_the_list(
    world: MailWorld, student: UserRef
) -> None:
    """UF-MAIL-02 2a: older than 30 days -> purged."""
    await world.deliver_and_parse(fixture_bytes("plain.eml"))
    world.clock.advance(days=31)

    page = await world.public.recent(student.id)

    assert page[0].purged
    assert page[0].subject == "Meeting tomorrow"


async def test_view_returns_text_html_and_attachments(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: summary, text, Telegram HTML, attachments as FileRef, truncated flag."""
    mail_id = await world.deliver_and_parse(fixture_bytes("html_image_link.eml"))

    view = await world.public.view(student.id, mail_id)

    assert view["summary"].id == mail_id
    assert view["summary"].subject == "New schedule"
    assert "<b>Aleksey</b>" in view["html_telegram"]
    assert "<img" not in view["html_telegram"]
    assert "Aleksey" in view["text"]
    assert view["attachments"] == []
    assert view["truncated"] is False


async def test_view_lists_stored_attachments_and_skipped_names(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: allowed attachments as files, others by name."""
    mail_id = await world.deliver_and_parse(fixture_bytes("pdf_and_exe.eml"))

    view = await world.public.view(student.id, mail_id)

    assert [a.name for a in view["attachments"]] == ["report.pdf"]
    assert view["skipped_attachments"] == ["setup.exe"]


async def test_view_marks_a_long_body_as_truncated(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-2: Show full is offered when the body was cut."""
    mail_id = await world.deliver_and_parse(make_raw(body="line of text\n" * 600))

    view = await world.public.view(student.id, mail_id)

    assert view["truncated"] is True
    assert len(view["html_telegram"]) <= 3500
    assert view["text"].count("line of text") == 600


async def test_view_of_a_mail_with_a_deleted_raw_file_is_the_summary_only(
    world: MailWorld, student: UserRef
) -> None:
    """UF-MAIL-02 2a, MAIL-7: only header and snippet are left."""
    mail_id = await world.deliver_and_parse(fixture_bytes("plain.eml"))
    raw_file = world.store.rows[mail_id].raw_file_id
    assert raw_file is not None
    world.files.delete(raw_file)

    view = await world.public.view(student.id, mail_id)

    assert view["summary"].purged is True
    assert view["summary"].snippet.startswith("Hello Aleksey")
    assert (
        view["text"] == "" and view["html_telegram"] == "" and view["attachments"] == []
    )


async def test_view_of_someone_elses_mail_is_not_found(world: MailWorld) -> None:
    """MAIL-2: mailboxes are private."""
    owner = world.student("owner.one")
    other = world.student("other.two")
    created = await world.deliver(
        fixture_bytes("plain.eml"), recipients=["owner.one@mail.ihsu.uz"]
    )

    with pytest.raises(MailNotFoundError):
        await world.public.view(other.id, created[0])
    assert owner.id != other.id


async def test_send_returns_the_summary_of_the_queued_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: MailApi.send."""
    summary = await world.public.send(
        student.id, to=["a@example.org"], subject="Hi", html="Hello"
    )

    assert (summary.direction, summary.subject, summary.snippet) == (
        "out",
        "Hi",
        "Hello",
    )
    assert summary.to == ("a@example.org",)
    assert summary.from_address == "aleksey.brastilov@mail.ihsu.uz"


async def test_reply_and_forward_return_summaries(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-4: MailApi.reply and MailApi.forward."""
    mail_id = await world.deliver_and_parse(fixture_bytes("plain.eml"))

    reply = await world.public.reply(student.id, mail_id, html="Thanks")
    forward = await world.public.forward(
        student.id, mail_id, to=["friend@example.org"], note_html=None
    )

    assert reply.subject == "Re: Meeting tomorrow"
    assert forward.subject == "Fwd: Meeting tomorrow"


async def test_marking_spam_and_undoing_it(world: MailWorld, student: UserRef) -> None:
    """UF-MAIL-04: Spam -> status spam (hidden); Undo -> back."""
    mail_id = await world.deliver_and_parse(fixture_bytes("plain.eml"))

    await world.public.mark_spam(student.id, mail_id, spam=True)
    assert world.store.rows[mail_id].status == MailStatus.SPAM
    assert await world.public.recent(student.id) == []

    await world.public.mark_spam(student.id, mail_id, spam=False)
    assert world.store.rows[mail_id].status == MailStatus.RECEIVED
    assert len(await world.public.recent(student.id)) == 1


async def test_undoing_spam_does_not_forward_a_mail_twice(
    world: MailWorld, student: UserRef
) -> None:
    """UF-MAIL-04: the original forward already used mail:{id}."""
    mail_id = await world.deliver_and_parse(fixture_bytes("plain.eml"))

    await world.public.mark_spam(student.id, mail_id, spam=True)
    await world.public.mark_spam(student.id, mail_id, spam=False)

    assert [n.dedupe_key for n in world.store.notifications] == [f"mail:{mail_id}"]


async def test_taking_an_automatic_spam_verdict_back_forwards_the_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-5: a false positive reaches Telegram once the student unmarks it."""
    world.authenticator.checks = InboundChecks(spf="fail")
    mail_id = await world.deliver_and_parse(make_raw(message_id=None))
    assert world.store.notifications == []

    await world.public.mark_spam(student.id, mail_id, spam=False)

    assert [(n.type, n.payload) for n in world.store.notifications] == [
        (NotificationType.MAIL, {"mail_id": str(mail_id)})
    ]


async def test_sent_mail_cannot_be_marked_as_spam(
    world: MailWorld, student: UserRef
) -> None:
    """UF-MAIL-04: only received mail."""
    sent = await world.public.send(
        student.id, to=["a@example.org"], subject="x", html="x"
    )

    with pytest.raises(NotAnInboundMailError):
        await world.public.mark_spam(student.id, sent.id, spam=True)


async def test_marking_someone_elses_mail_is_not_found(world: MailWorld) -> None:
    """UF-MAIL-04: mailboxes are private."""
    world.student("owner.one")
    other = world.student("other.two")
    created = await world.deliver(
        fixture_bytes("plain.eml"), recipients=["owner.one@mail.ihsu.uz"]
    )

    with pytest.raises(MailNotFoundError):
        await world.public.mark_spam(other.id, created[0], spam=True)


def test_the_address_of_a_login_is_in_the_mail_domain(world: MailWorld) -> None:
    """MAIL-1: {login}@mail.ihsu.uz."""
    assert (
        world.public.address_of("Brastilov.Aleksey") == "brastilov.aleksey@mail.ihsu.uz"
    )
