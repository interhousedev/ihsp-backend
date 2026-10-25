"""SQL and Redis reads behind the insights (read-only, no module owns them)."""

import asyncio
import datetime as dt
from collections.abc import Awaitable
from typing import Any, cast

from app.bootstrap.container import Container
from app.interfaces.http.main import _check_db, _check_redis
from app.interfaces.http.v1.admin_insights.schemas import StorageUsage, SystemHealth
from app.shared.clock import TASHKENT

from redis.exceptions import RedisError
from sqlalchemy import text

QUEUE_STREAM = "ihsp:jobs"
QUEUE_GROUP = "ihsp-workers"
_DAY = "(created_at AT TIME ZONE 'Asia/Tashkent')::date"


async def _day_counts(
    container: Container, sql: str, since: dt.datetime
) -> dict[Any, int]:
    async with container.engine.connect() as conn:
        rows = await conn.execute(text(sql), {"since": since})
        return {row[0]: int(row[1] or 0) for row in rows}


async def sign_ins_by_day(container: Container, since: dt.datetime) -> dict[Any, int]:
    """Distinct users that signed in, per day."""
    # nosec B608: _DAY is a module constant; the only value, :since, is bound.
    return await _day_counts(
        container,
        f"SELECT {_DAY} d, count(DISTINCT user_id) FROM id.audit_events "  # nosec B608
        "WHERE type = 'login.success' AND created_at >= :since GROUP BY d",
        since,
    )


async def ai_tokens_by_day(container: Container, since: dt.datetime) -> dict[Any, int]:
    """Tokens in and out of the assistant messages, per day."""
    # nosec B608: _DAY is a module constant; the only value, :since, is bound.
    return await _day_counts(
        container,
        f"SELECT {_DAY} d, "  # nosec B608
        "sum(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)) "
        "FROM ai.chat_messages WHERE created_at >= :since GROUP BY d",
        since,
    )


async def storage(container: Container) -> StorageUsage:
    """Ready uploads by scope."""
    async with container.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT scope, coalesce(sum(byte_size), 0), count(*) "
                "FROM files.files WHERE status = 'ready' GROUP BY scope"
            )
        )
        found = [(str(r[0]), int(r[1]), int(r[2])) for r in rows]
    return StorageUsage(
        bytes=sum(size for _, size, _ in found),
        files=sum(count for _, _, count in found),
        by_scope={scope: size for scope, size, _ in found},
    )


async def mark_counts(container: Container) -> dict[int, int]:
    """Marks by value."""
    async with container.engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT value, count(*) FROM academic.marks GROUP BY value")
        )
        return {int(r[0]): int(r[1]) for r in rows}


async def _logins(container: Container, since: dt.datetime) -> tuple[int, int]:
    async with container.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT type, count(*) FROM id.audit_events "
                "WHERE type IN ('login.success', 'login.failed') "
                "AND created_at >= :since GROUP BY type"
            ),
            {"since": since},
        )
        by_type = {str(r[0]): int(r[1]) for r in rows}
    return by_type.get("login.success", 0), by_type.get("login.failed", 0)


async def _queue(container: Container) -> tuple[int | None, int | None]:
    try:
        groups = await cast(
            Awaitable[list[dict[str, Any]]], container.redis.xinfo_groups(QUEUE_STREAM)
        )
    except (RedisError, OSError):
        return None, None
    for group in groups:
        if str(group.get("name")) == QUEUE_GROUP:
            lag = group.get("lag")
            return int(group.get("pending") or 0), None if lag is None else int(lag)
    return None, None


async def system_health(container: Container, now: dt.datetime) -> SystemHealth:
    """Liveness of PostgreSQL and Redis, the job queue and the last day of sign-ins."""
    db, redis = await asyncio.gather(_check_db(container), _check_redis(container))
    pending, lag = await _queue(container) if redis else (None, None)
    ok, failed = (
        await _logins(container, now - dt.timedelta(hours=24)) if db else (0, 0)
    )
    return SystemHealth(
        db=db,
        redis=redis,
        queue_pending=pending,
        queue_lag=lag,
        failed_logins_24h=failed,
        logins_24h=ok,
    )


def local_midnight_days_ago(now: dt.datetime, days: int) -> dt.datetime:
    """The start (Tashkent midnight) of the day `days - 1` days before today."""
    local = now.astimezone(TASHKENT)
    start = (local - dt.timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start
