"""SQL repository of broadcasts (Core statements on admin.broadcasts)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.broadcast import (
    Broadcast,
    BroadcastStats,
    BroadcastStatus,
    CreatedVia,
)
from app.modules.admin.domain.errors import BroadcastNotFoundError
from app.modules.admin.infrastructure.tables import broadcasts_table

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


def _stats_from_json(value: Mapping[str, Any] | None) -> BroadcastStats | None:
    if not value:
        return None
    return BroadcastStats(
        total=int(value.get("total", 0)),
        sent=int(value.get("sent", 0)),
        failed=int(value.get("failed", 0)),
        blocked=int(value.get("blocked", 0)),
    )


def _stats_to_json(stats: BroadcastStats | None) -> dict[str, int] | None:
    if stats is None:
        return None
    return {
        "total": stats.total,
        "sent": stats.sent,
        "failed": stats.failed,
        "blocked": stats.blocked,
    }


def _to_entity(row: RowMapping) -> Broadcast:
    return Broadcast(
        id=row["id"],
        author_id=row["author_id"],
        created_via=CreatedVia(row["created_via"]),
        title=row["title"],
        text=row["text"],
        audience=Audience.model_validate(row["audience"] or {}),
        created_at=row["created_at"],
        media_file_ids=list(row["media_file_ids"] or []),
        scheduled_at=row["scheduled_at"],
        status=BroadcastStatus(row["status"]),
        stats=_stats_from_json(row["stats"]),
    )


def _values(broadcast: Broadcast) -> dict[str, Any]:
    return {
        "title": broadcast.title,
        "text": broadcast.text,
        "media_file_ids": list(broadcast.media_file_ids),
        "audience": broadcast.audience.model_dump(mode="json"),
        "scheduled_at": broadcast.scheduled_at,
        "status": broadcast.status.value,
        "stats": _stats_to_json(broadcast.stats),
    }


class SqlBroadcastRepository:
    """Reads and writes broadcast rows in the unit of work's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session
        self.table = broadcasts_table()

    async def add(self, broadcast: Broadcast) -> None:
        """Insert a new broadcast."""
        values = {
            **_values(broadcast),
            "id": broadcast.id,
            "author_id": broadcast.author_id,
            "created_via": broadcast.created_via.value,
            "created_at": broadcast.created_at,
        }
        await self.session.execute(sa.insert(self.table).values(**values))

    async def get(self, broadcast_id: UUID, *, for_update: bool = False) -> Broadcast:
        """Return the broadcast, locking its row when asked."""
        stmt = sa.select(self.table).where(self.table.c.id == broadcast_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.session.execute(stmt)).mappings().first()
        if row is None:
            raise BroadcastNotFoundError(support_details=str(broadcast_id))
        return _to_entity(row)

    async def save(self, broadcast: Broadcast) -> None:
        """Store the editable fields, the status and the stats."""
        stmt = (
            sa.update(self.table)
            .where(self.table.c.id == broadcast.id)
            .values(**_values(broadcast))
        )
        await self.session.execute(stmt)

    async def list_page(
        self,
        *,
        status: BroadcastStatus | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Broadcast]:
        """Return broadcasts newest first."""
        c = self.table.c
        stmt = sa.select(self.table)
        if status is not None:
            stmt = stmt.where(c.status == status.value)
        if before is not None:
            stmt = stmt.where(
                sa.tuple_(c.created_at, c.id)
                < sa.tuple_(
                    sa.literal(before[0], type_=c.created_at.type),
                    sa.literal(before[1], type_=c.id.type),
                )
            )
        stmt = stmt.order_by(c.created_at.desc(), c.id.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [_to_entity(row) for row in rows]

    async def claim_scheduled(self, now: datetime) -> list[Broadcast]:
        """Lock scheduled broadcasts that are due; another worker skips them."""
        c = self.table.c
        stmt = (
            sa.select(self.table)
            .where(
                c.status == BroadcastStatus.SCHEDULED.value,
                c.scheduled_at <= now,
            )
            .order_by(c.scheduled_at, c.id)
            .with_for_update(skip_locked=True)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [_to_entity(row) for row in rows]

    async def list_sending(self) -> list[Broadcast]:
        """Return broadcasts that are being delivered."""
        c = self.table.c
        stmt = (
            sa.select(self.table)
            .where(c.status == BroadcastStatus.SENDING.value)
            .order_by(c.created_at, c.id)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [_to_entity(row) for row in rows]
