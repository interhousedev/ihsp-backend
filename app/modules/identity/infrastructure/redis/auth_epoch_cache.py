"""Cached auth_epoch per user (auth:epoch:{user_id})."""

from uuid import UUID

from redis.asyncio import Redis

EPOCH_TTL_SECONDS = 3600


class RedisAuthEpochCache:
    """The current epoch checked on every request; refreshed from the database."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    async def get(self, user_id: UUID) -> int | None:
        """Return the cached epoch or None."""
        value = await self._redis.get(f"auth:epoch:{user_id}")
        if value is None:
            return None
        return int(value.decode() if isinstance(value, bytes) else value)

    async def set(self, user_id: UUID, epoch: int) -> None:
        """Cache the epoch for an hour."""
        await self._redis.set(f"auth:epoch:{user_id}", epoch, ex=EPOCH_TTL_SECONDS)
