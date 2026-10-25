"""Redis counters of flash cards studied today (``fc:day:{user}:{block}:{date}``)."""

from collections.abc import Awaitable
from datetime import date
from typing import Final, cast
from uuid import UUID

from app.modules.lms.domain.learning.cards import DailyUsage

from redis.asyncio import Redis

DAY_TTL_SECONDS: Final = 48 * 3600


def _key(user_id: UUID, block_id: str, day: date) -> str:
    """Return the Redis key of one learner, block and day."""
    return f"fc:day:{user_id}:{block_id}:{day.isoformat()}"


class RedisDailyCounters:
    """Daily new and review counts of a flash card block, as a Redis hash."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def get(self, user_id: UUID, block_id: str, day: date) -> DailyUsage:
        """Return the cards introduced and reviewed today."""
        key = _key(user_id, block_id, day)
        values = cast(
            "Awaitable[list[bytes | str | None]]",
            self.redis.hmget(key, ["new", "review"]),
        )
        new, review = await values
        return DailyUsage(new=int(new or 0), review=int(review or 0))

    async def add(
        self, user_id: UUID, block_id: str, day: date, *, new: int = 0, review: int = 0
    ) -> None:
        """Count cards studied today; the key lives for 48 hours."""
        if not new and not review:
            return
        key = _key(user_id, block_id, day)
        async with self.redis.pipeline(transaction=True) as pipe:
            if new:
                pipe.hincrby(key, "new", new)
            if review:
                pipe.hincrby(key, "review", review)
            pipe.expire(key, DAY_TTL_SECONDS)
            await pipe.execute()
