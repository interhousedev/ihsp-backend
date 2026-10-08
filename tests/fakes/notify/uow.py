"""In-memory notification repository and unit of work."""

import copy
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.domain.notification_status import NotificationStatus
from app.shared.notifications import NotificationType


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

    async def purge_created_before(self, cutoff: datetime) -> int:
        """Delete old rows."""
        old = [nid for nid, n in self.rows.items() if n.created_at < cutoff]
        for nid in old:
            del self.rows[nid]
        return len(old)


class FakeNotifyUnitOfWork:
    """Implements NotifyUnitOfWork over an in-memory repository."""

    def __init__(self, repository: InMemoryNotificationRepository) -> None:
        """Share the repository between units of work."""
        self._repository = repository
        self.commits = 0

    @property
    def notifications(self) -> InMemoryNotificationRepository:
        """The shared repository."""
        return self._repository

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
