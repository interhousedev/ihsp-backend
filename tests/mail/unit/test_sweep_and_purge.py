"""MAIL-5, MAIL-7: the sweep and the daily purge."""

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.mail_status import MailStatus
from app.shared.contracts.identity import UserRef
from tests.mail.helpers import fixture_bytes, make_raw
from tests.mail.world import MailWorld


async def test_the_sweep_restarts_parsing_after_ten_minutes(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: received rows not parsed after 10 min are kicked again."""
    created = await world.deliver(fixture_bytes("plain.eml"))
    world.kicker.calls.clear()

    world.clock.advance(minutes=9)
    early = await world.sweep_mail.execute()
    world.clock.advance(minutes=2)
    late = await world.sweep_mail.execute()

    assert (early.parse, late.parse) == (0, 1)
    assert world.kicker.calls == [("mail.parse_inbound", {"mail_id": created[0]})]


async def test_the_sweep_leaves_parsed_mail_alone(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: parsed rows are done."""
    await world.deliver_and_parse(fixture_bytes("plain.eml"))
    world.kicker.calls.clear()
    world.clock.advance(minutes=30)

    result = await world.sweep_mail.execute()

    assert result.parse == 0
    assert world.kicker.calls == []


async def test_the_sweep_restarts_spam_parsing_too(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-5: spam is parsed (for its snippet) like other mail."""
    world.authenticator.checks = InboundChecks(spf="fail")
    await world.deliver(make_raw(message_id=None))
    world.clock.advance(minutes=11)

    assert (await world.sweep_mail.execute()).parse == 1


async def test_the_sweep_restarts_sending_of_old_queued_mail(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-6: queued rows older than 10 min are kicked again."""
    mail = await world.send_mail.execute(
        student.id, to=["a@example.org"], subject="x", html="x"
    )
    world.kicker.calls.clear()
    world.clock.advance(minutes=11)

    result = await world.sweep_mail.execute()

    assert result.send == 1
    assert world.kicker.calls == [("mail.send_outbound", {"mail_id": mail.id})]


async def test_sent_mail_is_not_swept(world: MailWorld, student: UserRef) -> None:
    """MAIL-6: only `queued` rows."""
    mail = await world.send_mail.execute(
        student.id, to=["a@example.org"], subject="x", html="x"
    )
    await world.deliver_outbound.execute(mail.id)
    world.kicker.calls.clear()
    world.clock.advance(minutes=30)

    assert (await world.sweep_mail.execute()).send == 0


async def test_spam_older_than_30_days_is_deleted(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-5: spam is kept for 30 days."""
    world.authenticator.checks = InboundChecks(spf="fail")
    old_spam = (await world.deliver(make_raw(message_id=None)))[0]
    world.clock.advance(days=20)
    newer_spam = (await world.deliver(make_raw(message_id=None, subject="newer")))[0]
    world.clock.advance(days=11)

    result = await world.purge_mail.execute()

    assert result.spam_deleted == 1
    assert old_spam not in world.store.rows
    assert newer_spam in world.store.rows


async def test_ordinary_mail_older_than_30_days_is_flagged_not_deleted(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: headers and snippet stay; meta.purged marks the missing raw file."""
    old = await world.deliver_and_parse(fixture_bytes("plain.eml"))
    world.clock.advance(days=31)

    result = await world.purge_mail.execute()

    assert result.flagged == 1
    row = world.store.rows[old]
    assert row.meta.purged
    assert row.subject == "Meeting tomorrow" and row.snippet


async def test_recent_mail_is_not_purged(world: MailWorld, student: UserRef) -> None:
    """MAIL-7: 29 days old is still complete."""
    recent = await world.deliver_and_parse(fixture_bytes("plain.eml"))
    world.clock.advance(days=29)

    result = await world.purge_mail.execute()

    assert (result.spam_deleted, result.flagged) == (0, 0)
    assert not world.store.rows[recent].meta.purged
    assert world.store.rows[recent].status == MailStatus.RECEIVED


async def test_purging_twice_flags_each_mail_once(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-7: the daily task is idempotent."""
    await world.deliver_and_parse(fixture_bytes("plain.eml"))
    world.clock.advance(days=31)
    await world.purge_mail.execute()

    again = await world.purge_mail.execute()

    assert again.flagged == 0
