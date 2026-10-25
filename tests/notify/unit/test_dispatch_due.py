"""The Telegram dispatcher (BOT-11–15, BOT-21, BOT-22, UF-BOT-04, UF-BOT-11)."""

from datetime import timedelta
from typing import Any

from app.modules.notify.application.dispatch_due import DispatchDue, DispatchReport
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import (
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.domain.telegram_errors import (
    TelegramBlocked,
    TelegramRetryAfter,
    TelegramSendFailed,
)
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.notifications import NotificationType
from tests.factories.notify import NOW, make_notification, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.limiter import CountingLimiter
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.fakes.notify.uow import InMemoryNotificationRepository

import pytest


async def _hello(payload: dict[str, Any], ctx: RenderContext) -> RenderedMessage:
    return RenderedMessage(
        text_html=f"hello {ctx.user.first_name}",
        buttons=[[{"text": "Open", "url": "https://example.test"}]],
    )


class Harness:
    """A dispatcher over in-memory fakes."""

    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.repo = InMemoryNotificationRepository()
        self.identity = FakeIdentityDirectory()
        self.sender = FakeTelegramSender()
        self.limiter = CountingLimiter()
        self.registry = RendererRegistry()
        for notification_type in (NotificationType.MARKS, NotificationType.MAIL):
            self.registry.register(notification_type, _hello)
        self.dispatch = DispatchDue(
            uow_factory=self.repo.uow,
            identity=self.identity,
            renderers=self.registry,
            sender=self.sender,
            limiter=self.limiter,
            clock=clock,
        )

    def user(self, *telegram_ids: int, **kwargs: Any) -> UserRef:
        return self.identity.add_user(make_user(**kwargs), *telegram_ids)

    def notification(
        self,
        user: UserRef,
        notification_type: NotificationType = NotificationType.MARKS,
        **kwargs: Any,
    ) -> Notification:
        return self.repo.add(make_notification(user.id, notification_type, **kwargs))

    def row(self, notification: Notification) -> Notification:
        return self.repo.get(notification.id)

    async def run(self) -> DispatchReport:
        return await self.dispatch.execute()


@pytest.fixture
def h(clock: FixedClock) -> Harness:
    return Harness(clock)


async def test_message_goes_to_every_linked_account_and_deliveries_are_recorded(
    h: Harness,
) -> None:
    """BOT-11: all linked Telegram accounts get the message once."""
    user = h.user(11, 22)
    n = h.notification(user)

    report = await h.run()

    assert [(m.chat_id, m.text_html) for m in h.sender.messages()] == [
        (11, "hello Aliya"),
        (22, "hello Aliya"),
    ]
    assert h.sender.messages()[0].buttons == [
        [{"text": "Open", "url": "https://example.test"}]
    ]
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.deliveries == {11: DeliveryState.SENT, 22: DeliveryState.SENT}
    assert row.sent_at == NOW
    assert row.attempts == 1
    assert (report.claimed, report.sent) == (1, 1)
    assert h.limiter.acquired == 2


async def test_retry_sends_only_to_the_account_that_failed(
    h: Harness, clock: FixedClock
) -> None:
    """BOT-11: a retry skips accounts that already got the message."""
    user = h.user(11, 22)
    n = h.notification(user)
    h.sender.fail_next(22, TelegramSendFailed("boom"))

    await h.run()

    row = h.row(n)
    assert row.status == NotificationStatus.PARTIAL
    assert row.deliveries == {11: DeliveryState.SENT, 22: DeliveryState.FAILED}
    assert row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(minutes=1)
    assert "boom" in (row.error or "")

    await h.run()
    assert len(h.sender.messages()) == 1  # not due yet

    clock.advance(minutes=1, seconds=1)
    await h.run()

    assert [m.chat_id for m in h.sender.messages()] == [11, 22]
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.attempts == 2
    assert row.error is None


async def test_blocked_account_is_marked_and_the_other_account_still_gets_it(
    h: Harness,
) -> None:
    """BOT-22, UF-BOT-11: blocked is not a failure and the link is flagged."""
    user = h.user(11, 22)
    n = h.notification(user)
    h.sender.fail_next(11, TelegramBlocked("bot was blocked by the user"))

    await h.run()

    assert h.identity.blocked_calls == [(11, True)]
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.deliveries == {11: DeliveryState.BLOCKED, 22: DeliveryState.SENT}


async def test_user_whose_only_account_blocks_the_bot_is_skipped(h: Harness) -> None:
    """UF-BOT-11: the notification is marked skipped and later ones aren't sent."""
    user = h.user(11)
    first = h.notification(user)
    h.sender.fail_next(11, TelegramBlocked("blocked"))

    await h.run()

    assert h.row(first).status == NotificationStatus.SKIPPED
    assert h.row(first).deliveries == {11: DeliveryState.BLOCKED}

    second = h.notification(user)
    await h.run()

    assert h.row(second).status == NotificationStatus.SKIPPED
    assert h.row(second).deliveries == {11: DeliveryState.BLOCKED}
    assert h.sender.messages() == []


async def test_flood_control_reschedules_the_row_and_the_rest_of_the_batch(
    h: Harness, clock: FixedClock
) -> None:
    """Telegram 429: nothing is lost, everything waits `retry_after` seconds."""
    users = [h.user(chat) for chat in (11, 22, 33)]
    rows = [h.notification(u) for u in users]
    h.sender.fail_next(11, TelegramRetryAfter(7))

    report = await h.run()

    assert report.rate_limited
    for n in rows:
        row = h.row(n)
        assert row.status == NotificationStatus.PENDING
        assert row.next_attempt_at == NOW + timedelta(seconds=7)
        assert row.attempts == 0
    assert h.sender.messages() == []

    clock.advance(seconds=8)
    report = await h.run()

    assert not report.rate_limited
    assert sorted(m.chat_id for m in h.sender.messages()) == [11, 22, 33]


async def test_flood_control_after_one_account_keeps_the_delivery(
    h: Harness, clock: FixedClock
) -> None:
    """Telegram 429 midway: the account that got the message is not sent to again."""
    user = h.user(11, 22)
    n = h.notification(user)
    h.sender.fail_next(22, TelegramRetryAfter(3))

    await h.run()

    row = h.row(n)
    assert row.status == NotificationStatus.PARTIAL
    assert row.deliveries == {11: DeliveryState.SENT}

    clock.advance(seconds=4)
    await h.run()

    assert [m.chat_id for m in h.sender.messages()] == [11, 22]


async def test_rows_that_are_not_due_are_left_alone(h: Harness) -> None:
    """BOT-15: lesson links wait for their time."""
    user = h.user(11)
    h.notification(user, scheduled_at=NOW + timedelta(minutes=5))

    report = await h.run()

    assert report.claimed == 0
    assert h.sender.messages() == []


async def test_expired_lease_makes_a_stuck_row_due_again(h: Harness) -> None:
    """A crashed dispatcher does not lose notifications."""
    user = h.user(11)
    n = h.notification(
        user,
        status=NotificationStatus.SENDING,
    )
    h.repo.rows[n.id].next_attempt_at = NOW - timedelta(minutes=1)

    await h.run()

    assert h.row(n).status == NotificationStatus.SENT


async def test_user_without_telegram_is_skipped(h: Harness) -> None:
    """UF-BOT-04: the web center keeps it, Telegram has nothing to send to."""
    user = h.user()
    n = h.notification(user)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "no-telegram"


@pytest.mark.parametrize(
    "status", [UserStatus.BLOCKED, UserStatus.DEACTIVATED, UserStatus.DELETED]
)
async def test_users_who_are_not_active_get_nothing(
    h: Harness, status: UserStatus
) -> None:
    """GEN-7: blocked and closed accounts are not messaged."""
    user = h.user(11, status=status)
    n = h.notification(user)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.sender.messages() == []


async def test_mail_is_skipped_when_forwarding_to_telegram_is_off(
    h: Harness,
) -> None:
    """MAIL-5: the user switched forwarding off."""
    user = h.user(11)
    prefs = await h.identity.get_preferences(user.id)
    h.identity.preferences[user.id] = prefs.model_copy(
        update={"mail_forward_to_telegram": False}
    )
    n = h.notification(user, NotificationType.MAIL)
    other = h.notification(user, NotificationType.MARKS)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "preferences"
    assert h.row(other).status == NotificationStatus.SENT


async def test_renderer_returning_none_skips_the_notification(h: Harness) -> None:
    """UF-BOT-07 1a: nothing to show, nothing sent."""

    async def nothing(payload: dict[str, Any], ctx: RenderContext) -> None:
        return None

    h.registry.register(NotificationType.LESSON_RESOURCES, nothing)
    user = h.user(11)
    n = h.notification(user, NotificationType.LESSON_RESOURCES)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.sender.messages() == []


async def test_type_without_a_renderer_is_skipped(h: Harness) -> None:
    """The bot's renderers are not registered in this process."""
    user = h.user(11)
    n = h.notification(user, NotificationType.LESSON_PROMPT)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "no-renderer:lesson_prompt"


async def test_crashing_renderer_is_retried_and_does_not_stop_the_batch(
    h: Harness, clock: FixedClock
) -> None:
    """One broken payload must not block other users' messages."""

    async def broken(payload: dict[str, Any], ctx: RenderContext) -> RenderedMessage:
        raise KeyError("subject_name")

    h.registry.register(NotificationType.RESULT_DROP, broken)
    user = h.user(11)
    bad = h.notification(user, NotificationType.RESULT_DROP)
    good = h.notification(user, NotificationType.MARKS)

    await h.run()

    assert h.row(bad).status == NotificationStatus.PARTIAL
    assert h.row(bad).error == "render-failed:KeyError"
    assert h.row(bad).next_attempt_at == NOW + timedelta(minutes=1)
    assert h.row(good).status == NotificationStatus.SENT


async def test_notification_fails_after_the_third_retry(
    h: Harness, clock: FixedClock
) -> None:
    """BOT-11: 1, 5 and 30 minutes, then failed."""
    user = h.user(11)
    n = h.notification(user)

    for wait in (1, 5, 30):
        h.sender.fail_next(11, TelegramSendFailed("down"))
        await h.run()
        assert h.row(n).status == NotificationStatus.PARTIAL
        clock.advance(minutes=wait, seconds=1)
    h.sender.fail_next(11, TelegramSendFailed("down"))
    await h.run()

    row = h.row(n)
    assert row.status == NotificationStatus.FAILED
    assert row.attempts == 4
    assert row.next_attempt_at is None


async def test_documents_follow_the_message_and_a_failed_document_is_only_noted(
    h: Harness,
) -> None:
    """BOT-21: media go out as documents after the text."""

    async def with_files(
        payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage:
        return RenderedMessage(
            text_html="news", documents=(("a.pdf", b"A"), ("b.pdf", b"B"))
        )

    h.registry.register(NotificationType.BROADCAST, with_files)
    user = h.user(11)
    n = h.notification(user, NotificationType.BROADCAST)

    await h.run()

    assert [(i.kind, i.filename) for i in h.sender.items] == [
        ("message", None),
        ("document", "a.pdf"),
        ("document", "b.pdf"),
    ]
    assert h.row(n).status == NotificationStatus.SENT
    assert h.limiter.acquired == 3


async def test_a_failing_document_does_not_resend_the_text(h: Harness) -> None:
    """The text was delivered; retrying would show it twice."""

    async def with_file(payload: dict[str, Any], ctx: RenderContext) -> RenderedMessage:
        return RenderedMessage(text_html="news", documents=(("a.pdf", b"A"),))

    h.registry.register(NotificationType.BROADCAST, with_file)
    user = h.user(11)
    n = h.notification(user, NotificationType.BROADCAST)
    h.sender.fail_next_document(11, TelegramSendFailed("file too big"))

    await h.run()

    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert "a.pdf" in (row.error or "")
    assert len(h.sender.messages()) == 1


async def test_roles_do_not_matter_for_dispatch(h: Harness) -> None:
    """BOT-11: teachers and admins get notifications too."""
    teacher = h.identity.add_user(make_user(Role.TEACHER), 11)
    n = h.notification(teacher)

    await h.run()

    assert h.row(n).status == NotificationStatus.SENT
