"""SQL aggregates of the usage ledger for the AI analytics pages and MCP tools."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow
from app.modules.ai.infrastructure.usage_reader import NO_USER, TASHKENT
from app.modules.ai.ports.analytics import (
    RequestGroup,
    RequestStatsRow,
    SpendDailyRow,
    SpendGroup,
    SpendRow,
)

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

OTHER = "other"
TOP_REQUESTS = 20
NO_REQUEST = "task:"
NO_PIPELINE = "none"


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The half-open Tashkent-day range [start, end] (both dates inclusive)."""
    zone = ZoneInfo(TASHKENT)
    return (
        datetime.combine(start, time.min, tzinfo=zone),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
    )


def _in_range(start: datetime, end: datetime) -> Any:
    return (UsageEventRow.occurred_at >= start) & (UsageEventRow.occurred_at < end)


def _filters(
    start: datetime,
    end: datetime,
    request_id: str | None,
    pipeline: str | None,
    user_id: UUID | None,
) -> list[Any]:
    clauses = [_in_range(start, end)]
    if request_id is not None:
        clauses.append(UsageEventRow.request_id == request_id)
    if pipeline is not None:
        clauses.append(UsageEventRow.pipeline == pipeline)
    if user_id is not None:
        clauses.append(UsageEventRow.user_id == user_id)
    return clauses


def _request_key() -> Any:
    """The request a call belongs to; legacy calls group as `task:<task>`."""
    return func.coalesce(
        UsageEventRow.request_id, func.concat(NO_REQUEST, UsageEventRow.task)
    )


def _group_key(group_by: str) -> Any:
    if group_by == "day":
        return func.to_char(
            func.timezone(TASHKENT, UsageEventRow.occurred_at), "YYYY-MM-DD"
        )
    if group_by == "user":
        return func.coalesce(cast(UsageEventRow.user_id, String), NO_USER)
    if group_by == "pipeline":
        return func.coalesce(UsageEventRow.pipeline, NO_PIPELINE)
    return _request_key()


def _float(value: Any) -> float:
    return float(value) if value is not None else 0.0


class SqlAiAnalyticsReader:
    """Implements `AiAnalyticsReader` over the sessionmaker (read-only)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def request_stats(
        self,
        start: date,
        end: date,
        request_id: str | None,
        pipeline: str | None,
        user_id: UUID | None,
        group_by: RequestGroup,
    ) -> list[RequestStatsRow]:
        """Averages and totals grouped as asked, costliest first."""
        lo, hi = _bounds(start, end)
        key = _group_key(group_by).label("key")
        stmt = (
            select(
                key,
                func.count().label("calls"),
                func.count().filter(UsageEventRow.success.is_(False)).label("failed"),
                func.avg(UsageEventRow.prompt_tokens_est).label("pt"),
                func.avg(UsageEventRow.prompt_chars).label("pc"),
                func.avg(UsageEventRow.answer_chars).label("ac"),
                func.avg(UsageEventRow.output_tokens).label("ot"),
                func.avg(UsageEventRow.tool_calls).label("tc"),
                func.sum(UsageEventRow.cost_micro).label("cost"),
            )
            .where(*_filters(lo, hi, request_id, pipeline, user_id))
            .group_by(key)
            .order_by(func.sum(UsageEventRow.cost_micro).desc(), key)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            RequestStatsRow(
                key=str(row.key),
                calls=int(row.calls),
                failed=int(row.failed or 0),
                avg_prompt_tokens=_float(row.pt),
                avg_prompt_chars=_float(row.pc),
                avg_answer_chars=_float(row.ac),
                avg_output_tokens=_float(row.ot),
                avg_tool_calls=_float(row.tc),
                cost_micro=int(row.cost or 0),
            )
            for row in rows
        ]

    async def spend(
        self,
        start: date,
        end: date,
        by: SpendGroup,
        request_id: str | None,
        user_id: UUID | None,
        limit: int,
    ) -> list[SpendRow]:
        """Spend grouped by day, request or user, most expensive first."""
        lo, hi = _bounds(start, end)
        key = _group_key(by).label("key")
        stmt = (
            select(
                key,
                func.sum(UsageEventRow.cost_micro).label("cost"),
                func.count().label("calls"),
                func.count(func.distinct(UsageEventRow.user_id)).label("users"),
            )
            .where(*_filters(lo, hi, request_id, None, user_id))
            .group_by(key)
            .order_by(func.sum(UsageEventRow.cost_micro).desc(), key)
            .limit(limit)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            SpendRow(
                key=str(row.key),
                cost_micro=int(row.cost or 0),
                calls=int(row.calls),
                users=int(row.users or 0),
                user_id=_uuid_or_none(row.key) if by == "user" else None,
            )
            for row in rows
        ]

    async def spend_daily(
        self,
        start: date,
        end: date,
        request_id: str | None,
        user_id: UUID | None,
    ) -> list[SpendDailyRow]:
        """Spend per day and request; requests beyond the top twenty fold to `other`."""
        lo, hi = _bounds(start, end)
        day = _group_key("day").label("day")
        req = _request_key().label("request_id")
        stmt = (
            select(
                day,
                req,
                func.sum(UsageEventRow.cost_micro).label("cost"),
                func.count().label("calls"),
            )
            .where(*_filters(lo, hi, request_id, None, user_id))
            .group_by(day, req)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
        totals: dict[str, int] = defaultdict(int)
        for row in rows:
            totals[str(row.request_id)] += int(row.cost or 0)
        top = set(sorted(totals, key=lambda k: (-totals[k], k))[:TOP_REQUESTS])
        folded: dict[tuple[str, str], list[int]] = {}
        for row in rows:
            name = str(row.request_id) if str(row.request_id) in top else OTHER
            bucket = folded.setdefault((str(row.day), name), [0, 0])
            bucket[0] += int(row.cost or 0)
            bucket[1] += int(row.calls)
        return [
            SpendDailyRow(day=d, request_id=r, cost_micro=c, calls=n)
            for (d, r), (c, n) in sorted(folded.items())
        ]


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None
