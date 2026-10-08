"""The SQL notification repository against PostgreSQL."""

from datetime import timedelta
from uuid import UUID

from app.modules.notify.application.dispatch_due import BATCH_SIZE
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.domain.notification_status import (
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.infrastructure.repositories.notification_repository import (
    SqlNotificationRepository,
)
from app.shared.ids import new_id
from tests.factories.notify import NOW
from tests.notify.db import fetch_row, insert_notification

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

LEASE_UNTIL = NOW + timedelta(minutes=10)


@pytest.fixture
def repo(db_session: AsyncSession) -> SqlNotificationRepository:
    return SqlNotificationRepository(db_session)


async def test_claim_due_takes_due_rows_and_leases_them(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """BOT-11: due pending rows become `sending` with a lease."""
    user = new_id()
    due = await insert_notification(db_session, user)
    later = await insert_notification(
        db_session, user, scheduled_at=NOW + timedelta(minutes=5)
    )
    sent = await insert_notification(db_session, user, status="sent")

    claimed = await repo.claim_due(now=NOW, limit=10, lease_until=LEASE_UNTIL)

    assert [n.id for n in claimed] == [due]
    assert claimed[0].status == NotificationStatus.SENDING
    row = await fetch_row(db_session, due)
    assert (row["status"], row["next_attempt_at"]) == ("sending", LEASE_UNTIL)
    assert (await fetch_row(db_session, later))["status"] == "pending"
    assert (await fetch_row(db_session, sent))["status"] == "sent"


async def test_claim_due_respects_retry_time_lease_and_limit(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """BOT-11: partial rows wait for next_attempt_at; stale leases are reclaimed."""
    user = new_id()
    retry_ready = await insert_notification(
        db_session,
        user,
        status="partial",
        next_attempt_at=NOW - timedelta(seconds=1),
        scheduled_at=NOW - timedelta(hours=3),
    )
    retry_waiting = await insert_notification(
        db_session, user, status="partial", next_attempt_at=NOW + timedelta(minutes=1)
    )
    stale_lease = await insert_notification(
        db_session,
        user,
        status="sending",
        next_attempt_at=NOW - timedelta(minutes=1),
        scheduled_at=NOW - timedelta(hours=2),
    )
    active_lease = await insert_notification(
        db_session, user, status="sending", next_attempt_at=NOW + timedelta(minutes=5)
    )
    newest = await insert_notification(db_session, user, scheduled_at=NOW)

    claimed = await repo.claim_due(now=NOW, limit=2, lease_until=LEASE_UNTIL)

    assert [n.id for n in claimed] == [retry_ready, stale_lease]  # oldest first
    rest = await repo.claim_due(now=NOW, limit=10, lease_until=LEASE_UNTIL)
    assert [n.id for n in rest] == [newest]
    assert (await fetch_row(db_session, retry_waiting))["status"] == "partial"
    assert (await fetch_row(db_session, active_lease))["status"] == "sending"


async def test_save_delivery_round_trips_the_delivery_state(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """BOT-11: per-account results survive a save and a claim."""
    notification_id = await insert_notification(db_session, new_id())
    (claimed,) = await repo.claim_due(now=NOW, limit=10, lease_until=LEASE_UNTIL)
    claimed.status = NotificationStatus.PARTIAL
    claimed.record(11, DeliveryState.SENT)
    claimed.record(22, DeliveryState.FAILED)
    claimed.attempts = 1
    claimed.next_attempt_at = NOW + timedelta(minutes=1)
    claimed.error = "22:boom"

    await repo.save_delivery(claimed)

    row = await fetch_row(db_session, notification_id)
    assert row["status"] == "partial"
    assert row["deliveries"] == {"11": "sent", "22": "failed"}
    assert row["attempts"] == 1
    assert row["error"] == "22:boom"
    later = await repo.claim_due(
        now=NOW + timedelta(minutes=2), limit=10, lease_until=LEASE_UNTIL
    )
    assert later[0].deliveries == {11: DeliveryState.SENT, 22: DeliveryState.FAILED}


async def test_center_lists_own_visible_rows_newest_first_with_filters(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """WEB-27: filters, user scope, scheduled-later and preview rows hidden."""
    user, other = new_id(), new_id()
    marks = await insert_notification(
        db_session, user, "marks", created_at=NOW - timedelta(minutes=3)
    )
    announcement = await insert_notification(
        db_session, user, "broadcast", created_at=NOW - timedelta(minutes=2)
    )
    changed = await insert_notification(
        db_session, user, "lesson_changed", created_at=NOW - timedelta(minutes=1)
    )
    await insert_notification(db_session, other, "marks")
    await insert_notification(
        db_session, user, "marks", scheduled_at=NOW + timedelta(hours=1)
    )
    await insert_notification(db_session, user, "broadcast", payload={"preview": True})

    async def ids(notification_filter: NotificationFilter) -> list[UUID]:
        rows = await repo.list_for_user(
            user, notification_filter, now=NOW, before=None, limit=50
        )
        return [n.id for n in rows]

    assert await ids(NotificationFilter.ALL) == [changed, announcement, marks]
    assert await ids(NotificationFilter.ACTIVITY) == [changed, marks]
    assert await ids(NotificationFilter.ANNOUNCEMENTS) == [announcement]


async def test_keyset_cursor_continues_after_the_last_row(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """WEB-27: pages do not overlap even with equal timestamps."""
    user = new_id()
    created = [NOW - timedelta(minutes=m) for m in (0, 1, 1, 2)]
    for moment in created:
        await insert_notification(db_session, user, created_at=moment)

    first = await repo.list_for_user(
        user, NotificationFilter.ALL, now=NOW, before=None, limit=2
    )
    second = await repo.list_for_user(
        user,
        NotificationFilter.ALL,
        now=NOW,
        before=(first[-1].created_at, first[-1].id),
        limit=2,
    )

    ids = [n.id for n in first + second]
    assert len(ids) == 4 == len(set(ids))


async def test_unread_count_and_marking_read(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """UF-WEB-15: unread count, mark one, mark all."""
    user, other = new_id(), new_id()
    a = await insert_notification(db_session, user)
    await insert_notification(db_session, user)
    await insert_notification(db_session, user, scheduled_at=NOW + timedelta(hours=1))
    foreign = await insert_notification(db_session, other)

    assert await repo.unread_count(user, now=NOW) == 2
    assert await repo.mark_read(user, a, now=NOW) is True
    assert await repo.mark_read(user, foreign, now=NOW) is False
    assert await repo.unread_count(user, now=NOW) == 1
    assert await repo.mark_all_read(user, now=NOW) == 1
    assert await repo.unread_count(user, now=NOW) == 0
    assert await repo.unread_count(other, now=NOW) == 1
    assert (await fetch_row(db_session, a))["read_at"] == NOW


async def test_read_time_is_kept_when_marked_again(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """UF-WEB-15: the first read time wins."""
    user = new_id()
    n = await insert_notification(db_session, user)
    await repo.mark_read(user, n, now=NOW)

    await repo.mark_read(user, n, now=NOW + timedelta(hours=1))

    assert (await fetch_row(db_session, n))["read_at"] == NOW


async def test_purge_deletes_rows_created_before_the_cutoff(
    db_session: AsyncSession, repo: SqlNotificationRepository
) -> None:
    """Notification: kept 90 days."""
    user = new_id()
    old = await insert_notification(
        db_session, user, created_at=NOW - timedelta(days=91)
    )
    fresh = await insert_notification(
        db_session, user, created_at=NOW - timedelta(days=89)
    )

    deleted = await repo.purge_created_before(NOW - timedelta(days=90))

    assert deleted == 1
    remaining = await repo.list_for_user(
        user, NotificationFilter.ALL, now=NOW, before=None, limit=10
    )
    assert [n.id for n in remaining] == [fresh]
    assert old not in [n.id for n in remaining]


def test_batch_size_is_one_hundred() -> None:
    """The dispatcher claims up to 100 rows per batch."""
    assert BATCH_SIZE == 100
