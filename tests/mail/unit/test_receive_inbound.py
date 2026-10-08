"""MAIL-5, MAIL-7, MAIL-9: accepting a message into the mailboxes."""

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.contracts.identity import UserRef
from tests.mail.fakes import InMemoryMailRepository
from tests.mail.helpers import ADDRESS, fixture_bytes, make_raw
from tests.mail.world import MailWorld

import pytest


async def test_the_raw_message_is_stored_for_30_days_and_the_row_is_recorded(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7, MAIL-9: raw .eml in S3 (scope mail, 30 days), row with headers."""
    raw = fixture_bytes("plain.eml")

    created = await world.deliver(raw)

    assert len(created) == 1
    row = world.store.rows[created[0]]
    assert row.user_id == student.id
    assert row.direction == MailDirection.IN
    assert row.status == MailStatus.RECEIVED
    assert row.message_id == "<plain-1@example.com>"
    assert row.from_address == "anna@example.com"
    assert row.subject == "Meeting tomorrow"
    assert row.occurred_at == world.clock.now()
    assert row.raw_file_id is not None
    stored = world.files.refs[row.raw_file_id]
    assert (stored.owner_id, stored.scope, stored.purpose) == (
        student.id,
        FileScope.MAIL,
        FilePurpose.MAIL,
    )
    assert world.files.blobs[row.raw_file_id] == raw
    assert world.files.expires[row.raw_file_id] == 30


async def test_parsing_is_started_after_the_row_is_committed(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: mail.parse_inbound(mail_id) is kicked."""
    created = await world.deliver(fixture_bytes("plain.eml"))

    assert world.kicker.calls == [("mail.parse_inbound", {"mail_id": created[0]})]


async def test_the_check_results_are_recorded(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: meta.checks has SPF, DKIM and DMARC; the peer is passed to the checks."""
    world.authenticator.checks = InboundChecks(
        spf="pass", dkim="pass", dmarc="pass", dmarc_policy="reject"
    )

    created = await world.deliver(fixture_bytes("plain.eml"))

    row = world.store.rows[created[0]]
    assert row.meta.checks == world.authenticator.checks
    assert world.authenticator.calls == [
        {
            "peer_ip": "203.0.113.9",
            "mail_from": "anna@example.com",
            "helo": "mx.example.com",
        }
    ]


async def test_each_recipient_gets_their_own_copy(world: MailWorld) -> None:
    """MAIL-9: one raw file and one row per mailbox, even for repeated addresses."""
    first = world.student("aleksey.brastilov")
    second = world.student("maria.ivanova")

    created = await world.deliver(
        fixture_bytes("plain.eml"),
        recipients=[ADDRESS, "maria.ivanova@mail.ihsu.uz", ADDRESS.upper()],
    )

    assert len(created) == 2
    owners = {world.store.rows[i].user_id for i in created}
    assert owners == {first.id, second.id}
    assert len(world.files.refs) == 2


async def test_unknown_recipients_create_nothing(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: no mailbox -> nothing stored."""
    created = await world.deliver(
        fixture_bytes("plain.eml"), recipients=["nobody@mail.ihsu.uz"]
    )

    assert created == []
    assert world.files.refs == {}
    assert world.kicker.calls == []


async def test_a_retried_delivery_is_not_stored_twice(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: same Message-ID in the same mailbox is a duplicate."""
    raw = fixture_bytes("plain.eml")
    await world.deliver(raw)

    again = await world.deliver(raw)

    assert again == []
    assert len(world.store.rows) == 1
    assert len(world.files.refs) == 1


async def test_a_message_without_message_id_gets_a_stable_synthetic_one(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: the id is derived from the content, so a retry is still a duplicate."""
    raw = make_raw(message_id=None)

    first = await world.deliver(raw)
    second = await world.deliver(raw)

    row = world.store.rows[first[0]]
    assert row.message_id.startswith("<no-id-") and row.message_id.endswith(
        "@mail.ihsu.uz>"
    )
    assert second == []


async def test_a_spf_failure_without_message_id_is_spam(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-5, MAIL-9: 3 (SPF fail) + 2 (no Message-ID) = 5 -> spam."""
    world.authenticator.checks = InboundChecks(spf="fail")

    created = await world.deliver(make_raw(message_id=None))

    row = world.store.rows[created[0]]
    assert row.status == MailStatus.SPAM
    assert row.spam_score == 5
    assert row.meta.spam_reasons == ["spf-fail", "no-message-id"]


async def test_an_empty_message_without_message_id_is_not_spam(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: 2 + 2 = 4 stays below the threshold."""
    created = await world.deliver(make_raw(message_id=None, subject="", body=""))

    row = world.store.rows[created[0]]
    assert row.status == MailStatus.RECEIVED
    assert row.spam_score == 4


async def test_spam_is_stored_like_other_mail_for_30_days(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-5: spam is kept (and parsed) but never forwarded."""
    world.authenticator.checks = InboundChecks(
        spf="fail", dkim="fail", dmarc="fail", dmarc_policy="reject"
    )

    created = await world.deliver(fixture_bytes("plain.eml"))

    row = world.store.rows[created[0]]
    assert row.status == MailStatus.SPAM
    assert row.raw_file_id is not None
    assert world.files.expires[row.raw_file_id] == 30
    assert world.kicker.names() == ["mail.parse_inbound"]


async def test_a_parallel_delivery_of_the_same_mail_is_recorded_once(
    world: MailWorld, student: UserRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAIL-9: two connections pass the early check; the unique index decides."""
    raw = fixture_bytes("plain.eml")
    await world.deliver(raw)

    async def never_seen(self: object, user_id: object, message_id: str) -> bool:
        return False

    monkeypatch.setattr(InMemoryMailRepository, "inbound_exists", never_seen)

    again = await world.deliver(raw)

    assert again == []
    assert len(world.store.rows) == 1
    assert world.kicker.names() == ["mail.parse_inbound"]
