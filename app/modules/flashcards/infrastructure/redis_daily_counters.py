"""Redis counters of today's introduced and reviewed cards (README → Redis keys)."""

from collections.abc import Awaitable
from datetime import date, timedelta
from typing import TypeVar, cast
from uuid import UUID

from app.modules.flashcards.domain.study import DailyUsage
from app.modules.flashcards.ports.daily_counters import CounterKind

from redis.asyncio import Redis

DAY_TTL = timedelta(hours=48)
T = TypeVar("T")


async def _wait(call: Awaitable[T] | T) -> T:
    """Await a redis-py call (its stubs type async results as `Awaitable | value`)."""
    return await cast("Awaitable[T]", call)


def _count(fields: dict[str | bytes, str | bytes], name: str) -> int:
    value = fields.get(name, fields.get(name.encode(), 0))
    return int(value)


class RedisDailyCounters:
    """Implements DailyCounters with the hash `fc:day:{user}:{set}:{date}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @staticmethod
    def _key(owner_id: UUID, set_id: UUID, day: date) -> str:
        return f"fc:day:{owner_id}:{set_id}:{day.isoformat()}"

    async def usage(self, owner_id: UUID, set_id: UUID, day: date) -> DailyUsage:
        """Return the counters of one day (zeros when nothing was studied)."""
        fields = await _wait(self.redis.hgetall(self._key(owner_id, set_id, day)))
        return DailyUsage(new=_count(fields, "new"), review=_count(fields, "review"))

    async def increment(
        self, owner_id: UUID, set_id: UUID, day: date, kind: CounterKind
    ) -> None:
        """Count one introduced new card or one finished review (kept 48 hours)."""
        key = self._key(owner_id, set_id, day)
        await _wait(self.redis.hincrby(key, kind, 1))
        await self.redis.expire(key, int(DAY_TTL.total_seconds()))
