"""Redis counters for the AI token budgets (README → Redis keys)."""

from collections.abc import Awaitable
from datetime import date, datetime, timedelta
from typing import TypeVar, cast
from uuid import UUID

from app.modules.ai.ports.budget_store import SessionWindow

from redis.asyncio import Redis

DAY_TTL = timedelta(hours=48)
T = TypeVar("T")


async def _wait(call: Awaitable[T] | T) -> T:
    """Await a redis-py call (its stubs type async results as `Awaitable | value`)."""
    return await cast("Awaitable[T]", call)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class RedisBudgetStore:
    """Implements BudgetStore with `ai:session:{user}` and `ai:day:{user}:{date}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @staticmethod
    def _session_key(user_id: UUID) -> str:
        return f"ai:session:{user_id}"

    @staticmethod
    def _day_key(user_id: UUID, day: date) -> str:
        return f"ai:day:{user_id}:{day.isoformat()}"

    async def session(self, user_id: UUID) -> SessionWindow | None:
        """Return the open session window, if there is one."""
        raw = await _wait(self.redis.hgetall(self._session_key(user_id)))
        data = {_text(k): _text(v) for k, v in raw.items()}
        if "ends_at" not in data:
            return None
        return SessionWindow(
            used=int(data.get("used", "0")),
            ends_at=datetime.fromisoformat(data["ends_at"]),
        )

    async def open_session(self, user_id: UUID, ends_at: datetime) -> None:
        """Start a new window with zero tokens used; it expires at `ends_at`."""
        key = self._session_key(user_id)
        await self.redis.delete(key)
        fields = {"used": 0, "ends_at": ends_at.isoformat()}
        await _wait(self.redis.hset(key, mapping=fields))
        await self.redis.expireat(key, int(ends_at.timestamp()))

    async def add_session(self, user_id: UUID, tokens: int) -> None:
        """Add tokens to the open window."""
        await _wait(self.redis.hincrby(self._session_key(user_id), "used", tokens))

    async def day_used(self, user_id: UUID, day: date) -> int:
        """Return the tokens used on a Tashkent day."""
        value = await self.redis.get(self._day_key(user_id, day))
        return int(_text(value)) if value is not None else 0

    async def add_day(self, user_id: UUID, day: date, tokens: int) -> None:
        """Add tokens to a day's counter (kept for 48 hours)."""
        key = self._day_key(user_id, day)
        await _wait(self.redis.incrby(key, tokens))
        await self.redis.expire(key, int(DAY_TTL.total_seconds()))
