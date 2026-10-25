"""The web notification center use cases (WEB-27, UF-WEB-15)."""

from datetime import timedelta
from typing import Any

from app.modules.notify.application.count_unread import CountUnread
from app.modules.notify.application.list_notifications import ListNotifications
from app.modules.notify.application.mark_all_read import MarkAllRead
from app.modules.notify.application.mark_read import MarkRead
from app.modules.notify.application.public_api import NotifyApiImpl
from app.modules.notify.application.purge_old import PurgeOld
from app.modules.notify.domain.errors import NotificationNotFoundError
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.settings import UrlsSettings
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.factories.notify import NOW, make_notification, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.uow import InMemoryNotificationRepository

import pytest

URLS = UrlsSettings()


class Center:
    """The center's use cases over an in-memory repository."""

    def __init__(self, i18n: I18nCore, clock: FixedClock) -> None:
        self.repo = InMemoryNotificationRepository()
        self.identity = FakeIdentityDirectory()
        self.user = self.identity.add_user(make_user(Role.STUDENT, locale="en"))
        self.actor = Actor(user_id=self.user.id, roles=frozenset({Role.STUDENT}))
        common = {"uow_factory": self.repo.uow, "clock": clock}
        self.list = ListNotifications(
            identity=self.identity, i18n=i18n, urls=URLS, **common
        )
        self.unread = CountUnread(**common)
        self.mark = MarkRead(**common)
        self.mark_all = MarkAllRead(**common)
        self.purge = PurgeOld(**common)
        self.public = NotifyApiImpl(
            identity=self.identity, i18n=i18n, urls=URLS, **common
        )

    def add(
        self,
        notification_type: NotificationType = NotificationType.MARKS,
        *,
        minutes_ago: int = 0,
        **kwargs: Any,
    ) -> None:
        created = NOW - timedelta(minutes=minutes_ago)
        payload = (
            {"title": "T", "text": "body"}
            if notification_type == NotificationType.BROADCAST
            else {}
        )
        self.repo.add(
            make_notification(
                self.user.id,
                notification_type,
                payload=payload,
                scheduled_at=created,
                created_at=created,
                **kwargs,
            )
        )


@pytest.fixture
def center(i18n: I18nCore, clock: FixedClock) -> Center:
    return Center(i18n, clock)


async def test_filters_split_announcements_from_activity(center: Center) -> None:
    """UF-WEB-15 step 2: Activity and Announcements tabs."""
    center.add(NotificationType.MARKS, minutes_ago=3)
    center.add(NotificationType.BROADCAST, minutes_ago=2)
    center.add(NotificationType.LESSON_CHANGED, minutes_ago=1)

    everything = await center.list.execute(center.actor, NotificationFilter.ALL)
    activity = await center.list.execute(center.actor, NotificationFilter.ACTIVITY)
    announcements = await center.list.execute(
        center.actor, NotificationFilter.ANNOUNCEMENTS
    )

    assert [i.type for i in everything.items] == [
        "lesson_changed",
        "broadcast",
        "marks",
    ]
    assert [i.type for i in activity.items] == ["lesson_changed", "marks"]
    assert [i.type for i in announcements.items] == ["broadcast"]
    assert announcements.items[0].title == "T"
    assert announcements.items[0].body == "body"


async def test_items_are_described_in_the_users_language(
    i18n: I18nCore, clock: FixedClock
) -> None:
    """WEB-27: titles come from the user's locale."""
    c = Center(i18n, clock)
    c.identity.users[c.user.id] = make_user(
        Role.STUDENT, locale="ru", user_id=c.user.id
    )
    c.add(NotificationType.EMIS_REAUTH)

    page = await c.list.execute(c.actor)

    assert page.items[0].title == "Нужен пароль EMIS"
    assert page.items[0].link == f"{URLS.id}/security/emis/"


async def test_pages_follow_the_cursor_without_gaps_or_repeats(center: Center) -> None:
    """WEB-27: cursor pagination, newest first."""
    for minutes in range(5):
        center.add(minutes_ago=minutes)

    first = await center.list.execute(center.actor, limit=2)
    second = await center.list.execute(center.actor, cursor=first.next_cursor, limit=2)
    third = await center.list.execute(center.actor, cursor=second.next_cursor, limit=2)

    ids = [i.id for page in (first, second, third) for i in page.items]
    assert len(ids) == 5 == len(set(ids))
    assert first.next_cursor and second.next_cursor
    assert third.next_cursor is None
    created = [i.created_at for page in (first, second, third) for i in page.items]
    assert created == sorted(created, reverse=True)


async def test_garbage_cursor_is_a_validation_error(center: Center) -> None:
    """WEB-27: a broken cursor is a 422, not a crash."""
    with pytest.raises(ValidationFailedError):
        await center.list.execute(center.actor, cursor="not-a-cursor")


async def test_notifications_scheduled_for_later_are_not_listed_or_counted(
    center: Center,
) -> None:
    """BOT-15: lesson links appear when they are due."""
    center.add(minutes_ago=0)
    center.repo.add(
        make_notification(
            center.user.id, scheduled_at=NOW + timedelta(minutes=5), created_at=NOW
        )
    )

    page = await center.list.execute(center.actor)

    assert len(page.items) == 1
    assert await center.unread.execute(center.actor) == 1


async def test_unread_count_drops_when_items_are_read(center: Center) -> None:
    """UF-WEB-15 step 3 and 4: opening an item and Mark all as read."""
    for minutes in range(3):
        center.add(minutes_ago=minutes)
    page = await center.list.execute(center.actor)
    assert await center.unread.execute(center.actor) == 3

    await center.mark.execute(center.actor, page.items[0].id)
    assert await center.unread.execute(center.actor) == 2

    changed = await center.mark_all.execute(center.actor)
    assert changed == 2
    assert await center.unread.execute(center.actor) == 0


async def test_reading_someone_elses_notification_is_not_found(center: Center) -> None:
    """GEN-7: users only touch their own notifications."""
    other = make_notification(new_id())
    center.repo.add(other)

    with pytest.raises(NotificationNotFoundError):
        await center.mark.execute(center.actor, other.id)


async def test_reading_twice_keeps_the_first_read_time(
    center: Center, clock: FixedClock
) -> None:
    """UF-WEB-15: reading is idempotent."""
    center.add()
    page = await center.list.execute(center.actor)
    item_id = page.items[0].id
    await center.mark.execute(center.actor, item_id)
    first = center.repo.get(item_id).read_at

    clock.advance(hours=1)
    await center.mark.execute(center.actor, item_id)

    assert center.repo.get(item_id).read_at == first


async def test_public_api_returns_the_latest_announcements_as_dicts(
    center: Center,
) -> None:
    """WEB-3: the Today page shows the three latest announcements."""
    for minutes in range(5):
        center.add(NotificationType.BROADCAST, minutes_ago=minutes)
    center.add(NotificationType.MARKS)

    latest = await center.public.latest_announcements(center.user.id, limit=3)
    unread = await center.public.unread_count(center.user.id)

    assert len(latest) == 3
    assert {item["type"] for item in latest} == {"broadcast"}
    assert set(latest[0]) == {
        "id",
        "type",
        "title",
        "body",
        "link",
        "created_at",
        "read_at",
    }
    assert unread == 6


async def test_purge_deletes_notifications_older_than_90_days(
    center: Center, clock: FixedClock
) -> None:
    """Notification: kept 90 days."""
    center.add(minutes_ago=91 * 24 * 60)
    center.add(minutes_ago=89 * 24 * 60)

    deleted = await center.purge.execute()

    assert deleted == 1
    assert len(center.repo.rows) == 1
