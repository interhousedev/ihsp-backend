"""Storage port for notifications."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_filter import NotificationFilter


class NotificationRepository(Protocol):
    """Reads and updates notifications; inserts go through the outbox writer."""

    async def claim_due(
        self, *, now: datetime, limit: int, lease_until: datetime
    ) -> list[Notification]:
        """Lock due rows (SKIP LOCKED), mark them `sending` with a lease."""
        ...

    async def save_delivery(self, notification: Notification) -> None:
        """Store status, deliveries, attempts, next attempt, sent time and error."""
        ...

    async def list_for_user(
        self,
        user_id: UUID,
        notification_filter: NotificationFilter,
        *,
        now: datetime,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Notification]:
        """Return visible notifications, newest first, after the keyset cursor."""
        ...

    async def unread_count(self, user_id: UUID, *, now: datetime) -> int:
        """Count visible notifications without `read_at`."""
        ...

    async def mark_read(
        self, user_id: UUID, notification_id: UUID, *, now: datetime
    ) -> bool:
        """Set `read_at` if empty; return False when the user has no such row."""
        ...

    async def mark_all_read(self, user_id: UUID, *, now: datetime) -> int:
        """Set `read_at` on every unread visible row; return how many changed."""
        ...

    async def purge_created_before(self, cutoff: datetime) -> int:
        """Delete notifications created before the cutoff; return how many."""
        ...
