"""The SQL push subscription repository against PostgreSQL."""

from datetime import timedelta
from uuid import UUID

from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.domain.notification_status import DeliveryState
from app.modules.notify.domain.push_subscription import push_delivery_key
from app.modules.notify.infrastructure.repositories.notification_repository import (
    SqlNotificationRepository,
)
from app.modules.notify.infrastructure.repositories.push_subscription_repository import (  # noqa: E501
    SqlPushSubscriptionRepository,
)
from app.shared.ids import new_id
from tests.factories.notify import AUTH, NOW, P256DH
from tests.notify.db import insert_notification

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def repo(db_session: AsyncSession) -> SqlPushSubscriptionRepository:
    return SqlPushSubscriptionRepository(db_session)


async def _add(
    repo: SqlPushSubscriptionRepository,
    user_id: UUID,
    n: int,
    *,
    minutes: int = 0,
) -> UUID:
    return await repo.upsert(
        user_id=user_id,
        endpoint=f"https://fcm.googleapis.com/fcm/send/{n}",
        p256dh=P256DH,
        auth=AUTH,
        user_agent="UA",
        now=NOW + timedelta(minutes=minutes),
    )


async def test_upsert_stores_the_subscription(
    repo: SqlPushSubscriptionRepository,
) -> None:
    """The row has the keys, the agent, the time and no failures."""
    user = new_id()

    subscription_id = await _add(repo, user, 1)

    (row,) = await repo.list_for_user(user)
    assert row.id == subscription_id
    assert (row.endpoint, row.p256dh, row.auth, row.user_agent) == (
        "https://fcm.googleapis.com/fcm/send/1",
        P256DH,
        AUTH,
        "UA",
    )
    assert (row.created_at, row.last_success_at, row.failures) == (NOW, None, 0)


async def test_the_same_endpoint_moves_to_the_new_user_and_keeps_its_id(
    repo: SqlPushSubscriptionRepository,
) -> None:
    """A shared browser: the last person to sign in owns the device."""
    first, second = new_id(), new_id()
    original = await _add(repo, first, 1)
    await repo.record_failure(original)

    moved = await _add(repo, second, 1, minutes=5)

    assert moved == original
    assert await repo.list_for_user(first) == []
    (row,) = await repo.list_for_user(second)
    assert row.failures == 0 and row.created_at == NOW + timedelta(minutes=5)


async def test_delete_by_endpoint_only_deletes_the_callers_row(
    repo: SqlPushSubscriptionRepository,
) -> None:
    """Someone else's endpoint cannot be removed."""
    owner, stranger = new_id(), new_id()
    await _add(repo, owner, 1)

    assert not await repo.delete_by_endpoint(
        stranger, "https://fcm.googleapis.com/fcm/send/1"
    )
    assert await repo.delete_by_endpoint(owner, "https://fcm.googleapis.com/fcm/send/1")
    assert not await repo.delete_by_endpoint(
        owner, "https://fcm.googleapis.com/fcm/send/1"
    )
    assert await repo.list_for_user(owner) == []


async def test_trim_keeps_the_newest_subscriptions(
    repo: SqlPushSubscriptionRepository,
) -> None:
    """Old devices fall off first, other users are untouched."""
    user, other = new_id(), new_id()
    for n in range(5):
        await _add(repo, user, n, minutes=n)
    await _add(repo, other, 99)

    removed = await repo.trim(user, keep=3)

    assert removed == 2
    kept = [row.endpoint.rsplit("/", 1)[1] for row in await repo.list_for_user(user)]
    assert kept == ["2", "3", "4"]
    assert len(await repo.list_for_user(other)) == 1


async def test_success_and_failure_bookkeeping(
    repo: SqlPushSubscriptionRepository,
) -> None:
    """Failures count up, a success resets them and sets the time."""
    user = new_id()
    subscription_id = await _add(repo, user, 1)

    assert await repo.record_failure(subscription_id) == 1
    assert await repo.record_failure(subscription_id) == 2
    await repo.record_success([subscription_id], NOW + timedelta(hours=1))

    (row,) = await repo.list_for_user(user)
    assert (row.failures, row.last_success_at) == (0, NOW + timedelta(hours=1))
    assert await repo.record_failure(new_id()) == 0  # a deleted row


async def test_delete_many(repo: SqlPushSubscriptionRepository) -> None:
    """Dropping several devices at once."""
    user = new_id()
    keep = await _add(repo, user, 1)
    drop = [await _add(repo, user, 2), await _add(repo, user, 3)]

    await repo.delete_many(drop)
    await repo.delete_many([])

    assert [row.id for row in await repo.list_for_user(user)] == [keep]


async def test_deliveries_of_both_channels_round_trip(
    db_session: AsyncSession,
) -> None:
    """Telegram ids stay integers and push keys stay strings in `deliveries`."""
    notifications = SqlNotificationRepository(db_session)
    notification_id = await insert_notification(db_session, new_id())
    (claimed,) = await notifications.claim_due(
        now=NOW, limit=5, lease_until=NOW + timedelta(minutes=10)
    )
    key = push_delivery_key(new_id())
    claimed.record(11, DeliveryState.SENT)
    claimed.record(key, DeliveryState.FAILED)

    await notifications.save_delivery(claimed)
    claimed.next_attempt_at = NOW - timedelta(seconds=1)
    await notifications.save_delivery(claimed)

    (reloaded,) = await notifications.list_for_user(
        claimed.user_id, NotificationFilter.ALL, now=NOW, before=None, limit=5
    )
    assert reloaded.id == notification_id
    assert reloaded.deliveries == {11: DeliveryState.SENT, key: DeliveryState.FAILED}
