"""MAIL-8, UF-ADM-15: automatic suspension after a bounce spike."""

from datetime import timedelta
from uuid import UUID

from app.modules.mail.domain.mail_status import MailStatus
from app.shared.contracts.identity import UserRef
from app.shared.notifications import NotificationType
from tests.mail.world import MailWorld

NO_AGE = timedelta()


async def _bounce(
    world: MailWorld, user: UserRef, count: int, *, age: timedelta = NO_AGE
) -> list[UUID]:
    """Send ``count`` mails and let them all bounce ``age`` ago."""
    ids = []
    for number in range(count):
        mail = await world.send_mail.execute(
            user.id, to=[f"gone{number}@example.org"], subject=f"s{number}", html="x"
        )
        row = world.store.rows[mail.id]
        row.mark_bounced(world.clock.now() - age, "550 5.1.1")
        ids.append(mail.id)
    return ids


async def test_five_bounces_in_a_day_suspend_the_mailbox(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: >= 5 bounces in 24 h -> suspended, student told, audited."""
    await _bounce(world, student, 5)

    suspended = await world.check_bounces.execute()

    assert suspended == [student.id]
    assert student.id in world.suspension.reasons
    assert [(n.user_id, n.type) for n in world.store.notifications] == [
        (student.id, NotificationType.MAIL_SUSPENDED)
    ]
    assert world.store.notifications[0].payload == {
        "reason": world.suspension.reasons[student.id]
    }
    [audit] = world.store.audits
    assert (audit.type, audit.user_id, audit.actor_id) == (
        "mail.suspended",
        student.id,
        None,
    )
    assert audit.metadata is not None
    assert audit.metadata["auto"] is True and audit.metadata["bounces"] == 5


async def test_four_bounces_are_not_enough(world: MailWorld, student: UserRef) -> None:
    """MAIL-8: the threshold is five."""
    await _bounce(world, student, 4)

    assert await world.check_bounces.execute() == []
    assert world.suspension.reasons == {}


async def test_old_bounces_do_not_count(world: MailWorld, student: UserRef) -> None:
    """MAIL-8: only the last 24 hours."""
    await _bounce(world, student, 3)
    await _bounce(world, student, 3, age=timedelta(hours=25))

    assert await world.check_bounces.execute() == []


async def test_other_students_bounces_are_not_added_up(world: MailWorld) -> None:
    """MAIL-8: the count is per mailbox."""
    first = world.student("first.student")
    second = world.student("second.student")
    await _bounce(world, first, 3)
    await _bounce(world, second, 3)

    assert await world.check_bounces.execute() == []


async def test_an_already_suspended_mailbox_is_not_suspended_again(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: an administrator may have suspended it first."""
    await _bounce(world, student, 5)
    world.suspension.reasons[student.id] = "by an administrator"

    assert await world.check_bounces.execute() == []

    assert world.suspension.reasons[student.id] == "by an administrator"
    assert world.store.notifications == []


async def test_counted_bounces_do_not_suspend_again_after_a_resume(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: an administrator resumes; the hourly run must not undo it."""
    await _bounce(world, student, 5)
    await world.check_bounces.execute()
    world.suspension.resume(student.id)
    world.clock.advance(hours=1)

    assert await world.check_bounces.execute() == []
    assert student.id not in world.suspension.reasons


async def test_new_bounces_after_a_resume_count_again(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: a fresh spike suspends again."""
    await _bounce(world, student, 5)
    await world.check_bounces.execute()
    world.suspension.resume(student.id)
    world.clock.advance(hours=1)
    await _bounce(world, student, 5)

    assert await world.check_bounces.execute() == [student.id]


async def test_bounced_status_is_what_counts(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-8: failed or sent mails are not bounces."""
    ids = await _bounce(world, student, 5)
    world.store.rows[ids[0]].status = MailStatus.SENT

    assert await world.check_bounces.execute() == []
