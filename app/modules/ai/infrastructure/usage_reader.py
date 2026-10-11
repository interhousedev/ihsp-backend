"""SQL aggregates of the usage ledger for the admin reports."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.ai.domain.usage import GroupTotals, Totals, UserTotals
from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow

from sqlalchemy import Select, String, case, cast, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TASHKENT = "Asia/Tashkent"
NO_USER = "system"
_GROUP_COLUMNS: dict[str, Any] = {
    "task": UsageEventRow.task,
    "model": UsageEventRow.model,
    "role": UsageEventRow.role,
    "feature": UsageEventRow.feature,
}


def _sums() -> list[Any]:
    return [
        func.coalesce(func.sum(UsageEventRow.input_tokens), 0).label("tokens_in"),
        func.coalesce(func.sum(UsageEventRow.output_tokens), 0).label("tokens_out"),
        func.coalesce(func.sum(UsageEventRow.cached_tokens), 0).label("cached"),
        func.count().label("calls"),
        func.coalesce(
            func.sum(case((UsageEventRow.success.is_(False), 1), else_=0)), 0
        ).label("failed"),
        func.coalesce(func.sum(UsageEventRow.cost_micro), 0).label("cost_micro"),
    ]


def _in_range(start: datetime, end: datetime) -> Any:
    return (UsageEventRow.occurred_at >= start) & (UsageEventRow.occurred_at < end)


def _totals(row: Any) -> Totals:
    return Totals(
        tokens_in=int(row.tokens_in or 0),
        tokens_out=int(row.tokens_out or 0),
        cached=int(row.cached or 0),
        calls=int(row.calls or 0),
        failed=int(row.failed or 0),
        cost_micro=int(row.cost_micro or 0),
    )


def _group_expr(group_by: str) -> Any:
    if group_by == "day":
        return func.to_char(
            func.timezone(TASHKENT, UsageEventRow.occurred_at), "YYYY-MM-DD"
        )
    if group_by == "user":
        return func.coalesce(cast(UsageEventRow.user_id, String), NO_USER)
    return _GROUP_COLUMNS[group_by]


class SqlUsageReader:
    """Implements `UsageReader` over the sessionmaker (read-only transactions)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def totals(self, start: datetime, end: datetime) -> Totals:
        """The sums of the events in [start, end)."""
        statement = select(*_sums()).where(_in_range(start, end))
        async with self.sessionmaker() as session:
            row = (await session.execute(statement)).one()
        return _totals(row)

    async def grouped(
        self, start: datetime, end: datetime, group_by: str
    ) -> list[GroupTotals]:
        """The sums per group key and feature, ordered by key then feature."""
        key = _group_expr(group_by).label("key")
        statement: Select[Any] = (
            select(key, UsageEventRow.feature, *_sums())
            .where(_in_range(start, end))
            .group_by(key, UsageEventRow.feature)
            .order_by(key, UsageEventRow.feature)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(statement)).all()
        return [
            GroupTotals(key=str(row.key), feature=row.feature, totals=_totals(row))
            for row in rows
        ]

    async def top_users(
        self, start: datetime, end: datetime, limit: int
    ) -> list[UserTotals]:
        """The users with the largest cost; the role is that of their latest call."""
        roles = func.array_agg(
            aggregate_order_by(UsageEventRow.role, UsageEventRow.occurred_at.desc())
        )
        statement = (
            select(UsageEventRow.user_id, roles.label("roles"), *_sums())
            .where(_in_range(start, end) & UsageEventRow.user_id.is_not(None))
            .group_by(UsageEventRow.user_id)
            .order_by(
                func.coalesce(func.sum(UsageEventRow.cost_micro), 0).desc(),
                func.count().desc(),
            )
            .limit(limit)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(statement)).all()
        return [
            UserTotals(
                user_id=_uuid(row.user_id),
                role=(row.roles or ["staff"])[0],
                totals=_totals(row),
            )
            for row in rows
        ]


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
