"""SQLAlchemy repository of the MCP call log (id.mcp_call_log)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.identity.infrastructure.orm import McpCallLogRow, McpConnector
from app.modules.identity.ports.mcp_call_log import (
    McpCallEntry,
    McpCallFilter,
    McpToolSummary,
)
from app.shared.contracts.mcp_calls import McpCallRecord
from app.shared.ids import new_id
from app.shared.pagination import Page, decode_cursor, encode_cursor

from sqlalchemy import and_, case, delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entry(row: McpCallLogRow) -> McpCallEntry:
    outcome: Any = row.outcome
    return McpCallEntry(
        id=row.id,
        created_at=row.created_at,
        user_id=row.user_id,
        connector_id=row.connector_id,
        connector_name=row.connector_name,
        client_id=row.client_id,
        server=row.server,
        tool=row.tool,
        scope=row.scope,
        read_only=row.read_only,
        outcome=outcome,
        error_code=row.error_code,
        error_id=row.error_id,
        duration_ms=row.duration_ms,
        arguments=row.arguments,
        result_summary=row.result_summary,
        ip=row.ip,
    )


def _conditions(where: McpCallFilter) -> list[Any]:
    columns = (
        (McpCallLogRow.user_id, where.user_id),
        (McpCallLogRow.connector_id, where.connector_id),
        (McpCallLogRow.server, where.server),
        (McpCallLogRow.tool, where.tool),
        (McpCallLogRow.outcome, where.outcome),
    )
    found = [column == value for column, value in columns if value is not None]
    if where.since is not None:
        found.append(McpCallLogRow.created_at >= where.since)
    if where.until is not None:
        found.append(McpCallLogRow.created_at <= where.until)
    return found


class SqlMcpCallLogRepository:
    """McpCallLogRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the session of the caller's transaction."""
        self._session = session

    async def add(self, entry: McpCallRecord) -> None:
        """Insert one trace, copying the current name of its connector."""
        name = (
            select(McpConnector.name)
            .where(McpConnector.id == entry.connector_id)
            .scalar_subquery()
        )
        await self._session.execute(
            insert(McpCallLogRow).values(
                id=new_id(),
                connector_name=name,
                user_id=entry.user_id,
                connector_id=entry.connector_id,
                client_id=entry.client_id,
                server=entry.server,
                tool=entry.tool,
                scope=entry.scope,
                read_only=entry.read_only,
                outcome=entry.outcome,
                error_code=entry.error_code,
                error_id=entry.error_id,
                duration_ms=entry.duration_ms,
                arguments=entry.arguments,
                result_summary=entry.result_summary,
                ip=entry.ip,
            )
        )

    async def search(
        self, where: McpCallFilter, *, cursor: str | None, limit: int
    ) -> Page[McpCallEntry]:
        """Newest first with a (created_at, id) cursor."""
        stmt = (
            select(McpCallLogRow)
            .where(*_conditions(where))
            .order_by(McpCallLogRow.created_at.desc(), McpCallLogRow.id.desc())
            .limit(limit + 1)
        )
        decoded = decode_cursor(cursor)
        if decoded:
            at, last_id = _position(decoded)
            stmt = stmt.where(
                or_(
                    McpCallLogRow.created_at < at,
                    and_(McpCallLogRow.created_at == at, McpCallLogRow.id < last_id),
                )
            )
        rows = list((await self._session.scalars(stmt)).all())
        items = [_to_entry(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = encode_cursor(
                {"at": last.created_at.isoformat(), "id": str(last.id)}
            )
        return Page[McpCallEntry](items=items, next_cursor=next_cursor)

    async def summary(self, where: McpCallFilter) -> list[McpToolSummary]:
        """Calls and failures per server and tool, busiest first."""
        calls = func.count()
        errors = func.sum(case((McpCallLogRow.outcome != "ok", 1), else_=0))
        rows = await self._session.execute(
            select(McpCallLogRow.server, McpCallLogRow.tool, calls, errors)
            .where(*_conditions(where))
            .group_by(McpCallLogRow.server, McpCallLogRow.tool)
            .order_by(calls.desc(), McpCallLogRow.server, McpCallLogRow.tool)
        )
        return [
            McpToolSummary(server=server, tool=tool, calls=count, errors=int(failed))
            for server, tool, count, failed in rows.tuples()
        ]

    async def purge_before(self, cutoff: datetime, *, limit: int) -> int:
        """Delete up to `limit` rows older than the cutoff; return how many."""
        batch = (
            select(McpCallLogRow.id)
            .where(McpCallLogRow.created_at < cutoff)
            .limit(limit)
        )
        result = await self._session.execute(
            delete(McpCallLogRow)
            .where(McpCallLogRow.id.in_(batch))
            .returning(McpCallLogRow.id)
        )
        return len(result.all())


def _position(decoded: dict[str, Any]) -> tuple[datetime, UUID]:
    return datetime.fromisoformat(decoded["at"]), UUID(decoded["id"])
