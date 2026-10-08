"""SQL repository of notifications (Core statements on notify.notifications)."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_filter import NotificationFilter
from app.modules.notify.domain.notification_status import (
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.infrastructure.tables import notifications_table
from app.shared.notifications import NotificationType

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

_BROADCAST = NotificationType.BROADCAST.value


def _to_entity(row: RowMapping) -> Notification:
    return Notification(
        id=row["id"],
        user_id=row["user_id"],
        type=NotificationType(row["type"]),
        payload=dict(row["payload"] or {}),
        dedupe_key=row["dedupe_key"],
        scheduled_at=row["scheduled_at"],
        created_at=row["created_at"],
        broadcast_id=row["broadcast_id"],
        status=NotificationStatus(row["status"]),
        deliveries={
            int(key): DeliveryState(value)
            for key, value in (row["deliveries"] or {}).items()
        },
        attempts=row["attempts"] or 0,
        next_attempt_at=row["next_attempt_at"],
        sent_at=row["sent_at"],
        read_at=row["read_at"],
        error=row["error"],
    )


class SqlNotificationRepository:
    """Reads and updates notification rows in the unit of work's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session
        self.table = notifications_table()

    def _visible(self, user_id: UUID, now: datetime) -> list[sa.ColumnElement[bool]]:
        """Rows the user sees: own, already due, and not an admin's preview."""
        c = self.table.c
        return [
            c.user_id == user_id,
            c.scheduled_at <= now,
            c.payload["preview"].as_string().is_distinct_from("true"),
        ]

    # - - - Dispatcher - - -

    async def claim_due(
        self, *, now: datetime, limit: int, lease_until: datetime
    ) -> list[Notification]:
        """Lock due rows (SKIP LOCKED) and mark them `sending` until the lease ends."""
        c = self.table.c
        ready = sa.and_(
            c.status.in_(
                [NotificationStatus.PENDING.value, NotificationStatus.PARTIAL.value]
            ),
            c.scheduled_at <= now,
            sa.or_(c.next_attempt_at.is_(None), c.next_attempt_at <= now),
        )
        lease_expired = sa.and_(
            c.status == NotificationStatus.SENDING.value, c.next_attempt_at <= now
        )
        due_ids = (
            sa.select(c.id)
            .where(sa.or_(ready, lease_expired))
            .order_by(c.scheduled_at, c.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            sa.update(self.table)
            .where(c.id.in_(due_ids))
            .values(
                status=NotificationStatus.SENDING.value, next_attempt_at=lease_until
            )
            .returning(*self.table.c)
        )
        result = await self.session.execute(stmt)
        rows = [_to_entity(row) for row in result.mappings().all()]
        return sorted(rows, key=lambda n: (n.scheduled_at, n.id))

    async def save_delivery(self, notification: Notification) -> None:
        """Store the delivery state of one notification."""
        stmt = (
            sa.update(self.table)
            .where(self.table.c.id == notification.id)
            .values(
                status=notification.status.value,
                deliveries={
                    str(account): state.value
                    for account, state in notification.deliveries.items()
                },
                attempts=notification.attempts,
                next_attempt_at=notification.next_attempt_at,
                sent_at=notification.sent_at,
                error=notification.error,
            )
        )
        await self.session.execute(stmt)

    # - - - Notification center - - -

    async def list_for_user(
        self,
        user_id: UUID,
        notification_filter: NotificationFilter,
        *,
        now: datetime,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Notification]:
        """Return visible notifications, newest first."""
        c = self.table.c
        stmt = sa.select(self.table).where(*self._visible(user_id, now))
        if notification_filter == NotificationFilter.ANNOUNCEMENTS:
            stmt = stmt.where(c.type == _BROADCAST)
        elif notification_filter == NotificationFilter.ACTIVITY:
            stmt = stmt.where(c.type != _BROADCAST)
        if before is not None:
            stmt = stmt.where(
                sa.tuple_(c.created_at, c.id)
                < sa.tuple_(
                    sa.literal(before[0], type_=c.created_at.type),
                    sa.literal(before[1], type_=c.id.type),
                )
            )
        stmt = stmt.order_by(c.created_at.desc(), c.id.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return [_to_entity(row) for row in result.mappings().all()]

    async def unread_count(self, user_id: UUID, *, now: datetime) -> int:
        """Count visible rows without `read_at`."""
        stmt = (
            sa.select(sa.func.count())
            .select_from(self.table)
            .where(*self._visible(user_id, now), self.table.c.read_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def mark_read(
        self, user_id: UUID, notification_id: UUID, *, now: datetime
    ) -> bool:
        """Set `read_at` if empty; False when the user has no such row."""
        c = self.table.c
        stmt = (
            sa.update(self.table)
            .where(c.id == notification_id, c.user_id == user_id)
            .values(read_at=sa.func.coalesce(c.read_at, now))
            .returning(c.id)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def mark_all_read(self, user_id: UUID, *, now: datetime) -> int:
        """Set `read_at` on every unread visible row."""
        stmt = (
            sa.update(self.table)
            .where(*self._visible(user_id, now), self.table.c.read_at.is_(None))
            .values(read_at=now)
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        return int(result.rowcount)

    async def purge_created_before(self, cutoff: datetime) -> int:
        """Delete rows created before the cutoff."""
        stmt = sa.delete(self.table).where(self.table.c.created_at < cutoff)
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        return int(result.rowcount)
