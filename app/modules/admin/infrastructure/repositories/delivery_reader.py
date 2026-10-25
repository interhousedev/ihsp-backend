"""Counts the delivery of a broadcast from notify.notifications (read-only)."""

from uuid import UUID

from app.modules.admin.infrastructure.tables import notifications_table
from app.modules.admin.ports.delivery_reader import DeliveryCounts

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_OPEN = ("pending", "sending", "partial")


class SqlDeliveryReader:
    """Aggregates notification statuses; blocked users are not failures (BOT-22)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session
        self.table = notifications_table()

    async def counts(self, broadcast_id: UUID) -> DeliveryCounts:
        """Count by status; `blocked` are skipped rows that hit a blocked account."""
        c = self.table.c
        by_status = await self._by_status(broadcast_id)
        skipped = await self.session.execute(
            sa.select(c.deliveries).where(
                c.broadcast_id == broadcast_id, c.status == "skipped"
            )
        )
        blocked = sum(
            1 for (deliveries,) in skipped if "blocked" in (deliveries or {}).values()
        )
        return DeliveryCounts(
            total=sum(by_status.values()),
            sent=by_status.get("sent", 0),
            failed=by_status.get("failed", 0),
            blocked=blocked,
            open=sum(by_status.get(status, 0) for status in _OPEN),
        )

    async def _by_status(self, broadcast_id: UUID) -> dict[str, int]:
        c = self.table.c
        stmt = (
            sa.select(c.status, sa.func.count())
            .where(c.broadcast_id == broadcast_id)
            .group_by(c.status)
        )
        return {
            str(status): int(count)
            for status, count in await self.session.execute(stmt)
        }
