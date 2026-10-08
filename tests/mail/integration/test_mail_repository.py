"""The MailRepository contract, run against the in-memory fake and PostgreSQL."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.mail_message import MailMessage
from app.modules.mail.domain.mail_meta import MailMeta
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.modules.mail.infrastructure.uow import SqlMailUnitOfWork
from app.modules.mail.ports.unit_of_work import MailUnitOfWork
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.mail.fakes import FakeMailUnitOfWork, MailStore
from tests.mail.helpers import make_mail

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

UowFactory = Callable[[], MailUnitOfWork]
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["fake", "sql"])
def open_uow(
    request: pytest.FixtureRequest, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> UowFactory:
    """A unit of work factory over the fake or PostgreSQL (rolled back at the end)."""
    if request.param == "fake":
        store = MailStore()
        return lambda: FakeMailUnitOfWork(store)
    return lambda: SqlMailUnitOfWork(
        sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
    )


async def add(open_uow: UowFactory, *mails: MailMessage) -> None:
    async with open_uow() as uow:
        for mail in mails:
            assert await uow.mail.add(mail)
        await uow.commit()


async def test_a_mail_round_trips_with_all_its_fields(open_uow: UowFactory) -> None:
    """MAIL-7: headers, arrays, file ids, score and meta survive."""
    mail = make_mail(
        new_id(),
        to=["a@example.org", "b@example.org"],
        cc=["c@example.org"],
        in_reply_to="<root@example.com>",
        references=["<root@example.com>", "<mid@example.com>"],
        raw_file_id=new_id(),
        attachment_file_ids=[new_id(), new_id()],
        spam_score=2.5,
        meta=MailMeta(
            checks=InboundChecks(
                spf="pass",
                dkim="pass",
                dmarc="pass",
                dmarc_policy="reject",
                spf_domain="example.com",
                dkim_domains=("example.com",),
                from_domain="example.com",
            ),
            spam_reasons=["no-message-id"],
            skipped_attachments=["setup.exe"],
            parsed_at=NOW,
        ),
    )
    await add(open_uow, mail)

    async with open_uow() as uow:
        loaded = await uow.mail.get(mail.id)

    assert loaded == mail


async def test_the_same_message_id_twice_in_one_mailbox_is_a_duplicate(
    open_uow: UowFactory,
) -> None:
    """MAIL-9: unique (user, direction, Message-ID)."""
    user = new_id()
    await add(open_uow, make_mail(user))

    async with open_uow() as uow:
        assert not await uow.mail.add(make_mail(user))
        assert await uow.mail.add(make_mail(new_id()))  # another mailbox
        assert await uow.mail.add(make_mail(user, direction=MailDirection.OUT))
        await uow.commit()


async def test_get_owned_hides_other_mailboxes(open_uow: UowFactory) -> None:
    """MAIL-2: mailboxes are private."""
    owner, other = new_id(), new_id()
    mail = make_mail(owner)
    await add(open_uow, mail)

    async with open_uow() as uow:
        assert (await uow.mail.get_owned(owner, mail.id)) is not None
        assert await uow.mail.get_owned(other, mail.id) is None
        assert await uow.mail.get(new_id()) is None


async def test_save_replaces_the_row(open_uow: UowFactory) -> None:
    """MAIL-6: status and meta changes are stored."""
    mail = make_mail(new_id(), direction=MailDirection.OUT, status=MailStatus.QUEUED)
    await add(open_uow, mail)

    async with open_uow() as uow:
        loaded = await uow.mail.get(mail.id)
        assert loaded is not None
        loaded.mark_bounced(NOW, "550 5.1.1")
        loaded.snippet = "changed"
        await uow.mail.save(loaded)
        await uow.commit()
    async with open_uow() as uow:
        again = await uow.mail.get(mail.id)

    assert again is not None
    assert again.status == MailStatus.BOUNCED
    assert again.meta.bounced_at == NOW and again.meta.bounce_reason == "550 5.1.1"
    assert again.snippet == "changed"


async def test_inbound_exists_looks_at_received_mail_only(open_uow: UowFactory) -> None:
    """MAIL-9: duplicate check before storing the raw file."""
    user = new_id()
    await add(
        open_uow,
        make_mail(user, message_id="<in@example.com>"),
        make_mail(user, message_id="<out@mail.ihsu.uz>", direction=MailDirection.OUT),
    )

    async with open_uow() as uow:
        assert await uow.mail.inbound_exists(user, "<in@example.com>")
        assert not await uow.mail.inbound_exists(user, "<out@mail.ihsu.uz>")
        assert not await uow.mail.inbound_exists(new_id(), "<in@example.com>")


async def test_recent_is_newest_first_pages_and_hides_spam(
    open_uow: UowFactory,
) -> None:
    """MAIL-3: newest first, `before` cursor, no spam, own mailbox."""
    user = new_id()
    mails = [
        make_mail(
            user,
            message_id=f"<{i}@example.com>",
            occurred_at=NOW + timedelta(minutes=i),
        )
        for i in range(5)
    ]
    spam = make_mail(
        user,
        message_id="<spam@example.com>",
        status=MailStatus.SPAM,
        occurred_at=NOW + timedelta(hours=1),
    )
    foreign = make_mail(
        new_id(),
        message_id="<foreign@example.com>",
        occurred_at=NOW + timedelta(hours=2),
    )
    await add(open_uow, *mails, spam, foreign)

    async with open_uow() as uow:
        first = await uow.mail.recent(user, limit=3, before=None)
        second = await uow.mail.recent(user, limit=3, before=first[-1].occurred_at)

    assert [m.message_id for m in first] == [
        "<4@example.com>",
        "<3@example.com>",
        "<2@example.com>",
    ]
    assert [m.message_id for m in second] == ["<1@example.com>", "<0@example.com>"]


async def test_find_outbound_matches_the_users_sent_mail_by_message_id(
    open_uow: UowFactory,
) -> None:
    """MAIL-6: used to attach a bounce to the mail it is about."""
    user = new_id()
    sent = make_mail(
        user,
        message_id="<out-1@mail.ihsu.uz>",
        direction=MailDirection.OUT,
        status=MailStatus.SENT,
    )
    received = make_mail(user, message_id="<in-1@example.com>")
    await add(
        open_uow,
        sent,
        received,
        make_mail(
            new_id(), message_id="<out-2@mail.ihsu.uz>", direction=MailDirection.OUT
        ),
    )

    async with open_uow() as uow:
        found = await uow.mail.find_outbound(user, ["<x@y>", "<out-1@mail.ihsu.uz>"])
        assert found is not None and found.id == sent.id
        assert await uow.mail.find_outbound(user, ["<in-1@example.com>"]) is None
        assert await uow.mail.find_outbound(user, ["<out-2@mail.ihsu.uz>"]) is None
        assert await uow.mail.find_outbound(user, []) is None


async def test_unparsed_and_stale_queries(open_uow: UowFactory) -> None:
    """MAIL-9: the sweep finds unparsed received mail and queued sent mail."""
    user = new_id()
    old = NOW - timedelta(minutes=30)
    unparsed = make_mail(user, message_id="<a@x.com>", occurred_at=old)
    unparsed_spam = make_mail(
        user, message_id="<b@x.com>", occurred_at=old, status=MailStatus.SPAM
    )
    parsed = make_mail(
        user, message_id="<c@x.com>", occurred_at=old, meta=MailMeta(parsed_at=NOW)
    )
    fresh = make_mail(user, message_id="<d@x.com>", occurred_at=NOW)
    queued = make_mail(
        user,
        message_id="<e@x.com>",
        occurred_at=old,
        direction=MailDirection.OUT,
        status=MailStatus.QUEUED,
    )
    sent = make_mail(
        user,
        message_id="<f@x.com>",
        occurred_at=old,
        direction=MailDirection.OUT,
        status=MailStatus.SENT,
    )
    await add(open_uow, unparsed, unparsed_spam, parsed, fresh, queued, sent)

    async with open_uow() as uow:
        to_parse = await uow.mail.unparsed_inbound(NOW - timedelta(minutes=10), 10)
        to_send = await uow.mail.stale_queued(NOW - timedelta(minutes=10), 10)
        limited = await uow.mail.unparsed_inbound(NOW - timedelta(minutes=10), 1)

    assert sorted(to_parse) == sorted([unparsed.id, unparsed_spam.id])
    assert to_send == [queued.id]
    assert len(limited) == 1


def bounced(user: UUID, number: int, when: datetime) -> MailMessage:
    mail = make_mail(
        user,
        message_id=f"<b{number}@mail.ihsu.uz>",
        direction=MailDirection.OUT,
        status=MailStatus.BOUNCED,
        occurred_at=when - timedelta(minutes=1),
    )
    mail.meta.bounced_at = when
    return mail


async def test_bounce_counts_per_user_within_the_window(open_uow: UowFactory) -> None:
    """MAIL-8: >= minimum uncounted bounces since the moment."""
    spiky, calm = new_id(), new_id()
    since = NOW - timedelta(hours=24)
    rows = [bounced(spiky, i, NOW - timedelta(hours=i)) for i in range(5)]
    rows += [bounced(spiky, 10, NOW - timedelta(hours=30))]  # outside the window
    rows += [bounced(calm, i, NOW) for i in range(20, 24)]
    await add(open_uow, *rows)

    async with open_uow() as uow:
        counts = await uow.mail.users_with_bounces(since, 5)

    assert counts == {spiky: 5}


async def test_counted_bounces_are_left_out(open_uow: UowFactory) -> None:
    """MAIL-8: marked bounces never trigger a second suspension."""
    user = new_id()
    since = NOW - timedelta(hours=24)
    await add(open_uow, *[bounced(user, i, NOW) for i in range(5)])

    async with open_uow() as uow:
        await uow.mail.mark_bounces_counted(user, since)
        await uow.commit()
    async with open_uow() as uow:
        assert await uow.mail.users_with_bounces(since, 1) == {}


async def test_spam_older_than_the_cutoff_is_deleted(open_uow: UowFactory) -> None:
    """MAIL-5: spam rows go after 30 days; other rows stay."""
    user = new_id()
    cutoff = NOW - timedelta(days=30)
    old_spam = make_mail(
        user,
        message_id="<s1@x.com>",
        status=MailStatus.SPAM,
        occurred_at=cutoff - timedelta(days=1),
    )
    new_spam = make_mail(
        user,
        message_id="<s2@x.com>",
        status=MailStatus.SPAM,
        occurred_at=cutoff + timedelta(days=1),
    )
    old_ok = make_mail(
        user, message_id="<s3@x.com>", occurred_at=cutoff - timedelta(days=1)
    )
    await add(open_uow, old_spam, new_spam, old_ok)

    async with open_uow() as uow:
        assert await uow.mail.delete_spam_before(cutoff) == 1
        await uow.commit()
    async with open_uow() as uow:
        assert await uow.mail.get(old_spam.id) is None
        assert await uow.mail.get(new_spam.id) is not None
        assert await uow.mail.get(old_ok.id) is not None


async def test_old_rows_are_flagged_purged_once(open_uow: UowFactory) -> None:
    """MAIL-7: meta.purged is merged into the existing meta."""
    user = new_id()
    cutoff = NOW - timedelta(days=30)
    old = make_mail(
        user,
        message_id="<o@x.com>",
        occurred_at=cutoff - timedelta(days=1),
        meta=MailMeta(parsed_at=NOW, skipped_attachments=["a.exe"]),
    )
    recent = make_mail(
        user, message_id="<r@x.com>", occurred_at=cutoff + timedelta(days=1)
    )
    await add(open_uow, old, recent)

    async with open_uow() as uow:
        assert await uow.mail.flag_purged_before(cutoff) == 1
        assert await uow.mail.flag_purged_before(cutoff) == 0
        await uow.commit()
    async with open_uow() as uow:
        flagged = await uow.mail.get(old.id)
        untouched = await uow.mail.get(recent.id)

    assert flagged is not None and untouched is not None
    assert flagged.meta.purged
    assert flagged.meta.parsed_at == NOW and flagged.meta.skipped_attachments == [
        "a.exe"
    ]
    assert not untouched.meta.purged
