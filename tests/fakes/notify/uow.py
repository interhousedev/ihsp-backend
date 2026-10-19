"""In-memory notification repository and unit of work."""

import copy
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.notify.domain.course_broadcast import CourseBroadcast
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.domain.notification_status import NotificationStatus
from app.modules.notify.domain.push_subscription import PushSubscription
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType


class InMemoryPushSubscriptions:
    """Implements PushSubscriptionRepository over a dictionary keyed by id."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, PushSubscription] = {}

    def add(self, subscription: PushSubscription) -> PushSubscription:
        """Store a subscription and return it."""
        self.rows[subscription.id] = subscription
        return subscription

    def for_user(self, user_id: UUID) -> list[PushSubscription]:
        """Return the user's subscriptions (for assertions)."""
        return sorted(
            (s for s in self.rows.values() if s.user_id == user_id),
            key=lambda s: (s.created_at, str(s.id)),
        )

    async def upsert(
        self,
        *,
        user_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
        now: datetime,
    ) -> UUID:
        """Insert by endpoint or move the existing one to the user."""
        for row in self.rows.values():
            if row.endpoint == endpoint:
                row.user_id, row.p256dh, row.auth = user_id, p256dh, auth
                row.user_agent, row.created_at, row.failures = user_agent, now, 0
                return row.id
        created = PushSubscription(
            id=new_id(),
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            created_at=now,
        )
        self.rows[created.id] = created
        return created.id

    async def trim(self, user_id: UUID, keep: int) -> int:
        """Delete the user's oldest rows beyond `keep`."""
        mine = self.for_user(user_id)
        old = mine[: max(len(mine) - keep, 0)]
        for row in old:
            del self.rows[row.id]
        return len(old)

    async def delete_by_endpoint(self, user_id: UUID, endpoint: str) -> bool:
        """Delete the user's row with this endpoint."""
        for row in list(self.rows.values()):
            if row.user_id == user_id and row.endpoint == endpoint:
                del self.rows[row.id]
                return True
        return False

    async def list_for_user(self, user_id: UUID) -> list[PushSubscription]:
        """Return copies of the user's rows, oldest first."""
        return [copy.copy(s) for s in self.for_user(user_id)]

    async def delete_many(self, ids: Sequence[UUID]) -> None:
        """Delete rows by id."""
        for subscription_id in ids:
            self.rows.pop(subscription_id, None)

    async def record_success(self, ids: Sequence[UUID], now: datetime) -> None:
        """Set `last_success_at` and clear failures."""
        for subscription_id in ids:
            if subscription_id in self.rows:
                self.rows[subscription_id].last_success_at = now
                self.rows[subscription_id].failures = 0

    async def record_failure(self, subscription_id: UUID) -> int:
        """Count one failure."""
        row = self.rows.get(subscription_id)
        if row is None:
            return 0
        row.failures += 1
        return row.failures


def _due(n: Notification, now: datetime) -> bool:
    if n.status in (NotificationStatus.PENDING, NotificationStatus.PARTIAL):
        return n.scheduled_at <= now and (
            n.next_attempt_at is None or n.next_attempt_at <= now
        )
    if n.status == NotificationStatus.SENDING:
        return n.next_attempt_at is not None and n.next_attempt_at <= now
    return False


class InMemoryNotificationRepository:
    """Implements NotificationRepository with copies, like a database would."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, Notification] = {}
        self.push = InMemoryPushSubscriptions()

    def add(self, notification: Notification) -> Notification:
        """Store a copy and return the original."""
        self.rows[notification.id] = copy.deepcopy(notification)
        return notification

    def get(self, notification_id: UUID) -> Notification:
        """Return the stored row (not a copy) for assertions."""
        return self.rows[notification_id]

    def uow(self) -> "FakeNotifyUnitOfWork":
        """Build a unit of work over this repository (use as the factory)."""
        return FakeNotifyUnitOfWork(self)

    async def claim_due(
        self, *, now: datetime, limit: int, lease_until: datetime
    ) -> list[Notification]:
        """Claim due rows like the SQL repository: `sending` with a lease."""
        due = sorted(
            (n for n in self.rows.values() if _due(n, now)),
            key=lambda n: (n.scheduled_at, str(n.id)),
        )[:limit]
        for n in due:
            n.status = NotificationStatus.SENDING
            n.next_attempt_at = lease_until
        return [copy.deepcopy(n) for n in due]

    async def save_delivery(self, notification: Notification) -> None:
        """Replace the stored row."""
        self.rows[notification.id] = copy.deepcopy(notification)

    def _visible(self, user_id: UUID, now: datetime) -> list[Notification]:
        rows = [
            n
            for n in self.rows.values()
            if n.user_id == user_id
            and n.scheduled_at <= now
            and not n.payload.get("preview")
        ]
        return sorted(rows, key=lambda n: (n.created_at, str(n.id)), reverse=True)

    async def list_for_user(
        self,
        user_id: UUID,
        notification_filter: NotificationFilter,
        *,
        now: datetime,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Notification]:
        """Return visible rows, newest first."""
        broadcast = NotificationType.BROADCAST
        rows = self._visible(user_id, now)
        if notification_filter == NotificationFilter.ANNOUNCEMENTS:
            rows = [n for n in rows if n.type == broadcast]
        elif notification_filter == NotificationFilter.ACTIVITY:
            rows = [n for n in rows if n.type != broadcast]
        if before is not None:
            rows = [
                n
                for n in rows
                if (n.created_at, str(n.id)) < (before[0], str(before[1]))
            ]
        return [copy.deepcopy(n) for n in rows[:limit]]

    async def unread_count(self, user_id: UUID, *, now: datetime) -> int:
        """Count visible unread rows."""
        return sum(1 for n in self._visible(user_id, now) if n.read_at is None)

    async def mark_read(
        self, user_id: UUID, notification_id: UUID, *, now: datetime
    ) -> bool:
        """Set read_at on the user's row."""
        row = self.rows.get(notification_id)
        if row is None or row.user_id != user_id:
            return False
        row.read_at = row.read_at or now
        return True

    async def mark_all_read(self, user_id: UUID, *, now: datetime) -> int:
        """Set read_at on every unread visible row."""
        changed = 0
        for n in self._visible(user_id, now):
            if n.read_at is None:
                self.rows[n.id].read_at = now
                changed += 1
        return changed

    async def update_course_broadcast(
        self, course_broadcast_id: UUID, *, title: str, text: str, edited_at: datetime
    ) -> int:
        """Rewrite the payload like the SQL repository does."""
        changed = 0
        for n in self.rows.values():
            if n.payload.get("course_broadcast_id") == str(course_broadcast_id):
                n.payload = {
                    **n.payload,
                    "title": title,
                    "text": text,
                    "edited_at": edited_at.isoformat(),
                }
                changed += 1
        return changed

    async def dedupe_key_seen_since(self, prefix: str, since: datetime) -> bool:
        """Any row with the prefix created since."""
        return any(
            n.dedupe_key.startswith(prefix) and n.created_at >= since
            for n in self.rows.values()
        )

    async def purge_created_before(self, cutoff: datetime) -> int:
        """Delete old rows."""
        old = [nid for nid, n in self.rows.items() if n.created_at < cutoff]
        for nid in old:
            del self.rows[nid]
        return len(old)


class InMemoryCourseBroadcasts:
    """Implements CourseBroadcastRepository."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[CourseBroadcast] = []

    async def add(self, broadcast: CourseBroadcast) -> None:
        """Keep the broadcast."""
        self.rows.append(broadcast)

    async def get(self, broadcast_id: UUID) -> CourseBroadcast | None:
        """The stored broadcast."""
        return next((r for r in self.rows if r.id == broadcast_id), None)

    async def update(self, broadcast: CourseBroadcast) -> None:
        """Replace the stored copy."""
        self.rows = [broadcast if r.id == broadcast.id else r for r in self.rows]

    async def list_for_course(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseBroadcast]:
        """Newest first."""
        rows = [r for r in self.rows if r.course_id == course_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]


class FakeNotifyUnitOfWork:
    """Implements NotifyUnitOfWork over an in-memory repository."""

    def __init__(
        self,
        repository: InMemoryNotificationRepository,
        broadcasts: InMemoryCourseBroadcasts | None = None,
        outbox: list[NotificationDraft] | None = None,
    ) -> None:
        """Share the repository between units of work."""
        self._repository = repository
        self._broadcasts = broadcasts or InMemoryCourseBroadcasts()
        self.outbox: list[NotificationDraft] = [] if outbox is None else outbox
        self.commits = 0

    @property
    def course_broadcasts(self) -> InMemoryCourseBroadcasts:
        """The shared broadcast history."""
        return self._broadcasts

    def notify(self, *drafts: NotificationDraft) -> None:
        """Collect the drafts the way the outbox would."""
        self.outbox.extend(drafts)

    @property
    def notifications(self) -> InMemoryNotificationRepository:
        """The shared repository."""
        return self._repository

    @property
    def push_subscriptions(self) -> InMemoryPushSubscriptions:
        """The shared push subscriptions."""
        return self._repository.push

    async def __aenter__(self) -> Self:
        """Open (nothing to do)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close (nothing to do)."""

    async def commit(self) -> None:
        """Count the commit."""
        self.commits += 1
