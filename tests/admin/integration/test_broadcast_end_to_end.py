"""A broadcast from draft to finished stats, through the real SQL layers."""

from datetime import UTC, datetime, timedelta

from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.broadcast import BroadcastStatus
from app.modules.notify.domain.telegram_errors import TelegramBlocked
from app.shared.actor import Role
from tests.admin.conftest import Stack
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock


async def test_broadcast_is_delivered_counted_and_finished(
    stack: Stack, clock: FixedClock
) -> None:
    """BOT-21, BOT-22, UF-ADM-08: delivery, blocked users, frozen stats."""
    # Outbox rows are due at the database's now(); the clock must be past it.
    clock.set(datetime.now(UTC) + timedelta(days=1))
    admin, notify, identity = stack.admin, stack.notify, stack.identity
    identity.add_user(make_user(Role.STUDENT), 101, 102)
    identity.add_user(make_user(Role.STUDENT), 103)
    identity.add_user(make_user(Role.STUDENT), 104)
    identity.add_user(make_user(Role.STUDENT))  # no Telegram account
    stack.sender.fail_next(104, TelegramBlocked("bot was blocked by the user"))
    draft = await admin.create_broadcast.execute(
        stack.actor,
        title="Exams",
        text="<b>Monday</b>",
        media_file_ids=[],
        audience=Audience(roles=[Role.STUDENT]),
    )
    bid = draft.broadcast.id

    sent = await admin.send_broadcast.execute(stack.actor, bid)
    assert sent.broadcast.status == BroadcastStatus.SENDING
    assert sent.stats is not None and sent.stats.total == 4
    assert await admin.finish_broadcasts.execute() == 0  # nothing delivered yet

    report = await notify.dispatch_due.execute()

    assert report.claimed == 4
    assert sorted(m.chat_id for m in stack.sender.messages()) == [101, 102, 103]
    assert (report.sent, report.skipped) == (2, 2)
    live = await admin.get_broadcast.execute(stack.actor, bid)
    assert live.stats is not None
    assert (live.stats.total, live.stats.sent, live.stats.blocked) == (4, 2, 1)

    assert await admin.finish_broadcasts.execute() == 1

    done = await admin.get_broadcast.execute(stack.actor, bid)
    assert done.broadcast.status == BroadcastStatus.SENT
    assert done.stats is not None
    assert (done.stats.total, done.stats.sent) == (4, 2)
    assert (done.stats.failed, done.stats.blocked) == (0, 1)
    assert identity.blocked_calls == [(104, True)]


async def test_sending_the_same_broadcast_twice_does_not_duplicate_notifications(
    stack: Stack, clock: FixedClock
) -> None:
    """GEN-8: bc:{id}:{user} makes delivery idempotent (also for a resumed send)."""
    clock.set(datetime.now(UTC) + timedelta(days=1))
    stack.identity.add_user(make_user(Role.STUDENT), 111)
    draft = await stack.admin.create_broadcast.execute(
        stack.actor,
        title="T",
        text="x",
        media_file_ids=[],
        audience=Audience(roles=[Role.STUDENT]),
    )
    view = await stack.admin.send_broadcast.execute(stack.actor, draft.broadcast.id)
    deliver = stack.admin.finish_broadcasts.deliver
    recipients = await stack.admin.resolve_audience.execute(view.broadcast.audience)

    await deliver.execute(view.broadcast, recipients)
    report = await stack.notify.dispatch_due.execute()

    assert report.claimed == 1
    assert len(stack.sender.messages()) == 1


async def test_preview_reaches_only_the_admin_and_hides_from_the_center(
    stack: Stack, clock: FixedClock
) -> None:
    """UF-ADM-08 step 3: the preview goes to my Telegram, not to the stats."""
    clock.set(datetime.now(UTC) + timedelta(days=1))
    draft = await stack.admin.create_broadcast.execute(
        stack.actor,
        title="T",
        text="<i>x</i>",
        media_file_ids=[],
        audience=Audience(everyone=True),
    )

    await stack.admin.preview_broadcast.execute(stack.actor, draft.broadcast.id)
    await stack.notify.dispatch_due.execute()

    (message,) = stack.sender.messages()
    assert message.chat_id == 900
    assert message.text_html.startswith("<i>Preview</i>\n<b>T</b>")
    page = await stack.notify.list_notifications.execute(stack.actor)
    assert page.items == []
