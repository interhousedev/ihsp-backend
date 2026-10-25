"""Web Push as the second channel of the dispatcher (no network: a fake sender)."""

from datetime import timedelta
from typing import Any

from app.modules.notify.application.dispatch_due import DispatchDue, DispatchReport
from app.modules.notify.application.push_delivery import PushDelivery
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import (
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.domain.push_errors import PushGone, PushSendFailed
from app.modules.notify.domain.push_payload import MAX_PAYLOAD_BYTES
from app.modules.notify.domain.push_subscription import (
    MAX_FAILURES,
    PushSubscription,
    push_delivery_key,
)
from app.modules.notify.domain.telegram_errors import TelegramRetryAfter
from app.settings import Settings
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType
from tests.factories.notify import NOW, make_notification, make_subscription, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.limiter import CountingLimiter
from tests.fakes.notify.push_sender import FakePushSender
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.fakes.notify.uow import InMemoryNotificationRepository

import pytest


async def _hello(payload: dict[str, Any], ctx: RenderContext) -> RenderedMessage:
    return RenderedMessage(text_html=f"hello {ctx.user.first_name}")


class Harness:
    """A dispatcher with both channels over in-memory fakes."""

    def __init__(self, clock: FixedClock, i18n: I18nCore, settings: Settings) -> None:
        self.clock = clock
        self.repo = InMemoryNotificationRepository()
        self.identity = FakeIdentityDirectory()
        self.telegram = FakeTelegramSender()
        self.push = FakePushSender()
        self.push_limiter = CountingLimiter()
        self.registry = RendererRegistry()
        self.registry.register(NotificationType.MARKS, _hello)
        self.registry.register(NotificationType.MAIL, _hello)
        self.urls = settings.urls
        self.dispatch = DispatchDue(
            uow_factory=self.repo.uow,
            identity=self.identity,
            renderers=self.registry,
            sender=self.telegram,
            limiter=CountingLimiter(),
            clock=clock,
            push=PushDelivery(
                uow_factory=self.repo.uow,
                sender=self.push,
                limiter=self.push_limiter,
                i18n=i18n,
                urls=settings.urls,
                clock=clock,
            ),
        )

    def user(self, *telegram_ids: int, **kwargs: Any) -> UserRef:
        return self.identity.add_user(make_user(**kwargs), *telegram_ids)

    def device(self, user: UserRef, **kwargs: Any) -> PushSubscription:
        return self.repo.push.add(make_subscription(user.id, **kwargs))

    def notification(
        self,
        user: UserRef,
        notification_type: NotificationType = NotificationType.MARKS,
        **kwargs: Any,
    ) -> Notification:
        return self.repo.add(make_notification(user.id, notification_type, **kwargs))

    def row(self, notification: Notification) -> Notification:
        return self.repo.get(notification.id)

    async def set_prefs(self, user: UserRef, **update: Any) -> None:
        prefs = await self.identity.get_preferences(user.id)
        self.identity.preferences[user.id] = prefs.model_copy(update=update)

    async def run(self) -> DispatchReport:
        return await self.dispatch.execute()


@pytest.fixture
def h(clock: FixedClock, i18n: I18nCore, settings: Settings) -> Harness:
    return Harness(clock, i18n, settings)


async def test_a_user_without_telegram_gets_the_push_on_every_device(
    h: Harness,
) -> None:
    """Push is a channel of its own: web-only users are reached."""
    user = h.user()
    phone, laptop = h.device(user), h.device(
        user, created_at=NOW + timedelta(seconds=1)
    )
    n = h.notification(user)

    report = await h.run()

    assert (report.claimed, report.sent) == (1, 1)
    assert len(h.push.to(phone.id)) == 1 and len(h.push.to(laptop.id)) == 1
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.deliveries == {
        push_delivery_key(phone.id): DeliveryState.SENT,
        push_delivery_key(laptop.id): DeliveryState.SENT,
    }
    assert row.attempts == 1
    assert h.push_limiter.acquired == 2
    assert h.telegram.items == []


async def test_both_channels_receive_the_same_notification(h: Harness) -> None:
    """Telegram works as before and the devices get a push in the same pass."""
    user = h.user(11, 22)
    device = h.device(user)
    n = h.notification(user)

    await h.run()

    assert [m.chat_id for m in h.telegram.messages()] == [11, 22]
    assert len(h.push.to(device.id)) == 1
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.deliveries == {
        11: DeliveryState.SENT,
        22: DeliveryState.SENT,
        push_delivery_key(device.id): DeliveryState.SENT,
    }


async def test_push_off_in_the_preferences_keeps_telegram_only(h: Harness) -> None:
    """notify_push = false: the devices are not messaged, Telegram is."""
    user = h.user(11)
    device = h.device(user)
    await h.set_prefs(user, notify_push=False)
    n = h.notification(user)

    await h.run()

    assert h.push.items == []
    assert [m.chat_id for m in h.telegram.messages()] == [11]
    assert h.row(n).deliveries == {11: DeliveryState.SENT}
    assert device.id in h.repo.push.rows


async def test_push_off_and_no_telegram_is_skipped(h: Harness) -> None:
    """Nothing to send to: the web center still lists it."""
    user = h.user()
    h.device(user)
    await h.set_prefs(user, notify_push=False)
    n = h.notification(user)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "no-telegram"
    assert h.push.items == []


async def test_a_user_with_no_channel_is_skipped_as_no_channel(h: Harness) -> None:
    """Push is on but the user has neither Telegram nor a device."""
    n = h.notification(h.user())

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "no-channel"


async def test_without_a_push_channel_devices_are_ignored(
    clock: FixedClock,
) -> None:
    """PUSH__ENABLED=false: the dispatcher behaves as it did before push."""
    repo = InMemoryNotificationRepository()
    identity = FakeIdentityDirectory()
    user = identity.add_user(make_user())
    repo.push.add(make_subscription(user.id))
    n = repo.add(make_notification(user.id))
    dispatch = DispatchDue(
        uow_factory=repo.uow,
        identity=identity,
        renderers=RendererRegistry(),
        sender=FakeTelegramSender(),
        limiter=CountingLimiter(),
        clock=clock,
    )

    await dispatch.execute()

    assert repo.get(n.id).status == NotificationStatus.SKIPPED
    assert repo.get(n.id).error == "no-telegram"


async def test_mail_switch_off_stops_both_channels(h: Harness) -> None:
    """Per-type switches apply to Telegram and push alike (MAIL-5)."""
    user = h.user(11)
    h.device(user)
    await h.set_prefs(user, mail_forward_to_telegram=False)
    n = h.notification(user, NotificationType.MAIL)

    await h.run()

    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "preferences"
    assert h.push.items == [] and h.telegram.items == []


@pytest.mark.parametrize("error", [PushGone("status 410"), PushGone("status 404")])
async def test_gone_subscription_is_deleted_and_not_retried(
    h: Harness, error: PushGone
) -> None:
    """404 and 410 from the push service remove the device; the rest still sends."""
    user = h.user()
    dead, alive = h.device(user), h.device(user, created_at=NOW + timedelta(seconds=1))
    h.push.fail_next(dead.id, error)
    n = h.notification(user)

    await h.run()

    assert dead.id not in h.repo.push.rows
    assert alive.id in h.repo.push.rows
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.deliveries == {push_delivery_key(alive.id): DeliveryState.SENT}
    assert len(h.push.to(alive.id)) == 1


async def test_when_every_device_is_gone_the_notification_is_skipped(
    h: Harness,
) -> None:
    """No device and no Telegram is left to deliver to."""
    user = h.user()
    only = h.device(user)
    h.push.fail_next(only.id, PushGone("status 410"))
    n = h.notification(user)

    await h.run()

    assert h.repo.push.rows == {}
    assert h.row(n).status == NotificationStatus.SKIPPED
    assert h.row(n).error == "no-channel"


async def test_failed_send_counts_a_failure_and_retries_only_that_device(
    h: Harness, clock: FixedClock
) -> None:
    """Other errors follow the Telegram retry policy: 1, 5, 30 minutes."""
    user = h.user()
    flaky, steady = h.device(user), h.device(
        user, created_at=NOW + timedelta(seconds=1)
    )
    h.push.fail_next(flaky.id, PushSendFailed("status 503"))
    n = h.notification(user)

    await h.run()

    row = h.row(n)
    assert row.status == NotificationStatus.PARTIAL
    assert row.deliveries == {
        push_delivery_key(flaky.id): DeliveryState.FAILED,
        push_delivery_key(steady.id): DeliveryState.SENT,
    }
    assert row.next_attempt_at == NOW + timedelta(minutes=1)
    assert "status 503" in (row.error or "")
    assert h.repo.push.rows[flaky.id].failures == 1
    assert h.repo.push.rows[steady.id].last_success_at == NOW

    clock.advance(minutes=1, seconds=1)
    await h.run()

    assert len(h.push.to(steady.id)) == 1  # not sent twice
    assert len(h.push.to(flaky.id)) == 1
    row = h.row(n)
    assert row.status == NotificationStatus.SENT
    assert row.attempts == 2 and row.error is None
    assert h.repo.push.rows[flaky.id].failures == 0  # success resets the counter


async def test_push_gives_up_after_the_third_retry(
    h: Harness, clock: FixedClock
) -> None:
    """Same schedule as Telegram: three retries, then failed."""
    user = h.user()
    device = h.device(user)
    n = h.notification(user)

    for wait in (1, 5, 30):
        h.push.fail_next(device.id, PushSendFailed("down"))
        await h.run()
        assert h.row(n).status == NotificationStatus.PARTIAL
        clock.advance(minutes=wait, seconds=1)
    h.push.fail_next(device.id, PushSendFailed("down"))
    await h.run()

    assert h.row(n).status == NotificationStatus.FAILED
    assert h.row(n).attempts == 4


async def test_a_device_that_keeps_failing_is_dropped(h: Harness) -> None:
    """After MAX_FAILURES in a row the subscription is removed."""
    user = h.user()
    worn = h.device(user, failures=MAX_FAILURES - 1)
    h.push.fail_next(worn.id, PushSendFailed("timeout"))
    n = h.notification(user)

    await h.run()

    assert worn.id not in h.repo.push.rows
    assert h.row(n).deliveries == {}
    assert h.row(n).status == NotificationStatus.SKIPPED


async def test_payload_is_built_from_the_description(h: Harness) -> None:
    """Six keys; the text is plain and the url absolute."""
    user = h.user(locale="en")
    device = h.device(user)
    n = h.notification(
        user,
        NotificationType.RESULT_DROP,
        payload={
            "scope": "subject",
            "subject_name": "Algebra",
            "old": 4.5,
            "new": 3.9,
            "semester": 1,
        },
    )

    await h.run()

    (item,) = h.push.to(device.id)
    assert set(item.payload) == {
        "title",
        "body",
        "url",
        "tag",
        "notification_id",
        "type",
    }
    assert item.payload["type"] == "result_drop"
    assert item.payload["notification_id"] == str(n.id) == item.payload["tag"]
    assert item.payload["url"] == f"{h.urls.sp}/grades/"
    assert "Algebra" in item.payload["body"]
    assert item.payload["title"] and "<" not in item.payload["title"]
    assert len(item.raw.encode()) <= MAX_PAYLOAD_BYTES


async def test_payload_text_follows_the_user_locale(h: Harness) -> None:
    """The same notification reads differently in Russian."""
    user = h.user(locale="ru")
    device = h.device(user)
    english = h.user(locale="en")
    other = h.device(english)
    payload = {"title": "T", "text": "x"}
    h.notification(user, NotificationType.EMIS_REAUTH, payload=payload)
    h.notification(english, NotificationType.EMIS_REAUTH, payload=payload)

    await h.run()

    assert (
        h.push.to(device.id)[0].payload["title"]
        != h.push.to(other.id)[0].payload["title"]
    )


async def test_broadcast_html_becomes_plain_text_within_three_kilobytes(
    h: Harness,
) -> None:
    """A long announcement is cut; tags are removed; multi-byte text counts in bytes."""
    user = h.user()
    device = h.device(user)
    text = "<b>Важное</b><br>" + "объявление " * 400
    h.notification(
        user,
        NotificationType.BROADCAST,
        payload={"title": "<i>Экзамены</i>", "text": text},
    )

    await h.run()

    (item,) = h.push.to(device.id)
    assert item.payload["title"] == "Экзамены"
    assert "<" not in item.payload["body"] and item.payload["body"].endswith("…")
    assert len(item.raw.encode()) <= MAX_PAYLOAD_BYTES


async def test_notification_without_a_link_opens_the_notification_list(
    h: Harness,
) -> None:
    """A mail notice has no page of its own."""
    user = h.user()
    device = h.device(user)
    h.notification(user, NotificationType.MAIL)

    await h.run()

    assert h.push.to(device.id)[0].payload["url"] == f"{h.urls.sp}/notifications/"


async def test_teachers_are_sent_to_the_staff_app(h: Harness) -> None:
    """Lesson links use the portal the reader works in."""
    teacher = h.identity.add_user(make_user(Role.TEACHER))
    device = h.device(teacher)
    h.notification(
        teacher,
        NotificationType.LESSON_CHANGED,
        payload={"lesson_id": "abc", "subject_name": "Math", "changes": {}},
    )
    h.notification(teacher, NotificationType.MAIL)

    await h.run()

    urls = sorted(i.payload["url"] for i in h.push.to(device.id))
    assert urls == [
        f"{h.urls.staff}/lessons/view/?id=abc",
        f"{h.urls.staff}/notifications/",
    ]


async def test_push_goes_out_even_if_telegram_has_no_renderer(h: Harness) -> None:
    """lesson_prompt's renderer lives in the bot process; push uses the description."""
    teacher = h.identity.add_user(make_user(Role.TEACHER), 11)
    device = h.device(teacher)
    n = h.notification(
        teacher, NotificationType.LESSON_PROMPT, payload={"lesson_id": "x"}
    )

    await h.run()

    assert len(h.push.to(device.id)) == 1
    assert h.telegram.items == []
    assert h.row(n).status == NotificationStatus.SENT
    assert h.row(n).deliveries == {push_delivery_key(device.id): DeliveryState.SENT}


async def test_a_crashing_telegram_renderer_does_not_hold_back_the_push(
    h: Harness,
) -> None:
    """The device got it at once; only Telegram is retried."""

    async def broken(payload: dict[str, Any], ctx: RenderContext) -> RenderedMessage:
        raise KeyError("subject_name")

    h.registry.register(NotificationType.MARKS, broken)
    user = h.user(11)
    device = h.device(user)
    n = h.notification(user)

    await h.run()

    assert len(h.push.to(device.id)) == 1
    row = h.row(n)
    assert row.status == NotificationStatus.PARTIAL
    assert row.deliveries[push_delivery_key(device.id)] == DeliveryState.SENT
    assert row.deliveries[11] == DeliveryState.FAILED
    assert row.error == "render-failed:KeyError"


async def test_telegram_flood_control_keeps_the_push_delivery(
    h: Harness, clock: FixedClock
) -> None:
    """The device already has it; after the pause only Telegram is sent."""
    user = h.user(11)
    device = h.device(user)
    n = h.notification(user)
    h.telegram.fail_next(11, TelegramRetryAfter(5))

    report = await h.run()

    assert report.rate_limited
    row = h.row(n)
    assert row.status == NotificationStatus.PARTIAL
    assert row.deliveries == {push_delivery_key(device.id): DeliveryState.SENT}
    assert row.attempts == 0

    clock.advance(seconds=6)
    await h.run()

    assert len(h.push.to(device.id)) == 1
    assert [m.chat_id for m in h.telegram.messages()] == [11]
    assert h.row(n).status == NotificationStatus.SENT


async def test_other_users_devices_are_not_messaged(h: Harness) -> None:
    """Subscriptions belong to their user."""
    user, other = h.user(), h.user()
    mine, theirs = h.device(user), h.device(other)
    h.notification(user)

    await h.run()

    assert len(h.push.to(mine.id)) == 1
    assert h.push.to(theirs.id) == []


async def test_a_blocked_telegram_account_does_not_stop_the_push(h: Harness) -> None:
    """Telegram blocked is not a failure; the notification is sent through push."""
    user = h.identity.add_user(make_user(), 11, blocked=True)
    device = h.device(user)
    n = h.notification(user)

    await h.run()

    assert len(h.push.to(device.id)) == 1
    assert h.row(n).status == NotificationStatus.SENT
