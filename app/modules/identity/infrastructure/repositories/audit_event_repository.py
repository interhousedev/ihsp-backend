"""SQLAlchemy reader of audit events (id.audit_events)."""

from datetime import datetime
from uuid import UUID

from app.modules.identity.domain.audit_event import AuditEventRecord
from app.modules.identity.infrastructure.orm import AuditEvent as AuditRow
from app.shared.pagination import Page, decode_cursor, encode_cursor

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_record(row: AuditRow) -> AuditEventRecord:
    return AuditEventRecord(
        id=row.id,
        type=row.type,
        created_at=row.created_at,
        user_id=row.user_id,
        actor_id=row.actor_id,
        ip=row.ip,
        user_agent=row.user_agent,
        metadata=dict(row.meta or {}),
    )


class SqlAuditEventRepository:
    """AuditEventRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def search(
        self,
        *,
        user_id: UUID | None,
        type: str | None,
        since: datetime | None,
        until: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> Page[AuditEventRecord]:
        """Filter events; newest first with a (created_at, id) cursor."""
        stmt = (
            select(AuditRow)
            .order_by(AuditRow.created_at.desc(), AuditRow.id.desc())
            .limit(limit + 1)
        )
        if user_id is not None:
            stmt = stmt.where(AuditRow.user_id == user_id)
        if type:
            stmt = stmt.where(AuditRow.type == type)
        if since is not None:
            stmt = stmt.where(AuditRow.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditRow.created_at <= until)
        decoded = decode_cursor(cursor)
        if decoded:
            at = datetime.fromisoformat(decoded["at"])
            last_id = UUID(decoded["id"])
            stmt = stmt.where(
                or_(
                    AuditRow.created_at < at,
                    and_(AuditRow.created_at == at, AuditRow.id < last_id),
                )
            )
        rows = list((await self._session.scalars(stmt)).all())
        has_more = len(rows) > limit
        items = [_to_record(row) for row in rows[:limit]]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(
                {"at": last.created_at.isoformat(), "id": str(last.id)}
            )
        return Page[AuditEventRecord](items=items, next_cursor=next_cursor)

    async def recent_for_user(
        self, user_id: UUID, limit: int
    ) -> list[AuditEventRecord]:
        """The latest events of a user."""
        page = await self.search(
            user_id=user_id,
            type=None,
            since=None,
            until=None,
            cursor=None,
            limit=limit,
        )
        return page.items
