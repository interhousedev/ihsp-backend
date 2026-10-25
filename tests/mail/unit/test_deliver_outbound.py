"""MAIL-6: delivery through the external relay."""

from uuid import UUID

from app.modules.mail.domain.mail_status import MailStatus
from app.modules.mail.ports.outbound_relay import (
    RelayPermanentError,
    RelayTemporaryError,
)
from app.shared.contracts.identity import UserRef
from app.shared.notifications import NotificationType
from tests.mail.world import MailWorld


async def _queued(world: MailWorld, student: UserRef) -> UUID:
    mail = await world.send_mail.execute(
        student.id,
        to=["teacher@example.org", "other@example.org"],
        subject="Question",
        html="Hello",
    )
    return mail.id


async def test_a_queued_mail_is_sent_through_the_relay_and_marked_sent(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: the raw message goes out from the mailbox address to every recipient."""
    mail_id = await _queued(world, student)
    row = world.store.rows[mail_id]
    assert row.raw_file_id is not None

    await world.deliver_outbound.execute(mail_id)

    assert len(world.relay.calls) == 1
    call = world.relay.calls[0]
    assert call.sender == "aleksey.brastilov@mail.ihsu.uz"
    assert call.recipients == ("teacher@example.org", "other@example.org")
    assert call.raw == world.files.blobs[row.raw_file_id]
    sent = world.store.rows[mail_id]
    assert sent.status == MailStatus.SENT
    assert sent.meta.sent_at == world.clock.now()
    assert world.store.notifications == []


async def test_a_temporary_error_is_retried_with_backoff(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: retries with growing waits, then success."""
    mail_id = await _queued(world, student)
    world.relay.errors = [
        RelayTemporaryError("421 try later"),
        RelayTemporaryError("timeout"),
    ]

    await world.deliver_outbound.execute(mail_id)

    assert len(world.relay.calls) == 3
    assert world.sleep.delays == [2.0, 10.0]
    assert world.store.rows[mail_id].status == MailStatus.SENT


async def test_after_three_retries_the_mail_fails_and_the_student_is_told(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: retry 3x, then `failed` and a `mail_bounced` notification."""
    mail_id = await _queued(world, student)
    world.relay.errors = [RelayTemporaryError(f"421 attempt {i}") for i in range(4)]

    await world.deliver_outbound.execute(mail_id)

    assert len(world.relay.calls) == 4
    assert world.sleep.delays == [2.0, 10.0, 30.0]
    failed = world.store.rows[mail_id]
    assert failed.status == MailStatus.FAILED
    assert failed.meta.failed_reason == "421 attempt 3"
    assert [(n.type, n.payload) for n in world.store.notifications] == [
        (
            NotificationType.MAIL_BOUNCED,
            {
                "mail_id": str(mail_id),
                "to": ["teacher@example.org", "other@example.org"],
            },
        )
    ]


async def test_a_permanent_error_fails_at_once(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: 5xx from the relay is not retried."""
    mail_id = await _queued(world, student)
    world.relay.errors = [RelayPermanentError("550 relay denied")]

    await world.deliver_outbound.execute(mail_id)

    assert len(world.relay.calls) == 1
    assert world.sleep.delays == []
    assert world.store.rows[mail_id].status == MailStatus.FAILED
    assert [n.type for n in world.store.notifications] == [
        NotificationType.MAIL_BOUNCED
    ]


async def test_refused_recipients_are_recorded_but_the_mail_is_sent(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: the relay took the mail for the other recipients."""
    mail_id = await _queued(world, student)
    world.relay.refused = ("other@example.org",)

    await world.deliver_outbound.execute(mail_id)

    sent = world.store.rows[mail_id]
    assert sent.status == MailStatus.SENT
    assert sent.meta.refused_recipients == ["other@example.org"]


async def test_a_mail_is_sent_only_once(world: MailWorld, student: UserRef) -> None:
    """MAIL-6: the sweep may start the task again."""
    mail_id = await _queued(world, student)

    await world.deliver_outbound.execute(mail_id)
    await world.deliver_outbound.execute(mail_id)

    assert len(world.relay.calls) == 1


async def test_two_workers_do_not_send_the_same_mail_twice(
    world: MailWorld, student: UserRef, redis: object
) -> None:
    """MAIL-6: a second worker finds the send lock taken."""
    mail_id = await _queued(world, student)
    lock = world.deliver_outbound._lock  # noqa: SLF001
    assert await lock.acquire(f"mail:send:{mail_id}", 900)

    await world.deliver_outbound.execute(mail_id)

    assert world.relay.calls == []
    assert world.store.rows[mail_id].status == MailStatus.QUEUED


async def test_a_deleted_raw_file_fails_the_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: nothing left to send."""
    mail_id = await _queued(world, student)
    raw_file = world.store.rows[mail_id].raw_file_id
    assert raw_file is not None
    world.files.delete(raw_file)

    await world.deliver_outbound.execute(mail_id)

    assert world.store.rows[mail_id].status == MailStatus.FAILED
    assert world.relay.calls == []


async def test_received_mail_and_unknown_ids_are_ignored(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: only queued outbound mail is sent."""
    from tests.mail.helpers import fixture_bytes

    received = await world.deliver(fixture_bytes("plain.eml"))

    await world.deliver_outbound.execute(received[0])
    await world.deliver_outbound.execute(UUID(int=1))

    assert world.relay.calls == []


async def test_a_mail_without_a_raw_file_fails(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: nothing to send."""
    mail_id = await _queued(world, student)
    world.store.rows[mail_id].raw_file_id = None

    await world.deliver_outbound.execute(mail_id)

    assert world.store.rows[mail_id].status == MailStatus.FAILED
    assert world.relay.calls == []
