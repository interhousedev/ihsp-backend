"""Redis counter of the day's web searches."""

from collections.abc import Awaitable
from datetime import date, timedelta
from typing import TypeVar, cast
from uuid import UUID

from redis.asyncio import Redis

DAY_TTL = timedelta(hours=48)
T = TypeVar("T")


async def _wait(call: Awaitable[T] | T) -> T:
    """Await a redis-py call (its stubs type async results as `Awaitable | value`)."""
    return await cast("Awaitable[T]", call)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class RedisSearchQuotaStore:
    """Implements SearchQuotaStore with `ai:websearch:{user}:{date}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @staticmethod
    def _key(user_id: UUID, day: date) -> str:
        return f"ai:websearch:{user_id}:{day.isoformat()}"

    async def used(self, user_id: UUID, day: date) -> int:
        """Searches counted that day."""
        value = await self.redis.get(self._key(user_id, day))
        return int(_text(value)) if value is not None else 0

    async def add(self, user_id: UUID, day: date, units: int) -> int:
        """Count `units` searches; `INCRBY` makes two requests at once safe."""
        key = self._key(user_id, day)
        total = int(await _wait(self.redis.incrby(key, units)))
        await self.redis.expire(key, int(DAY_TTL.total_seconds()))
        return total

    async def remove(self, user_id: UUID, day: date, units: int) -> None:
        """Give searches back; the counter never goes below zero."""
        key = self._key(user_id, day)
        if int(await _wait(self.redis.decrby(key, units))) < 0:
            await self.redis.set(key, 0, ex=int(DAY_TTL.total_seconds()))
