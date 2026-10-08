"""Redis click counters (`links:hits:{link_id}`), flushed every five minutes."""

from collections.abc import Mapping
from uuid import UUID

from redis.asyncio import Redis

PREFIX = "links:hits:"


class RedisHitCounter:
    """Counts hits in Redis; the scheduler drains them into PostgreSQL."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def hit(self, link_id: UUID) -> None:
        """Count one click or view."""
        await self.redis.incr(f"{PREFIX}{link_id}")

    async def drain(self) -> dict[UUID, int]:
        """Take every counter and reset it atomically (GETDEL)."""
        counts: dict[UUID, int] = {}
        async for raw_key in self.redis.scan_iter(match=f"{PREFIX}*", count=500):
            key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            value = await self.redis.getdel(key)
            if value is not None and int(value) > 0:
                counts[UUID(key.removeprefix(PREFIX))] = int(value)
        return counts

    async def restore(self, counts: Mapping[UUID, int]) -> None:
        """Add the counters back after a failed flush."""
        for link_id, count in counts.items():
            await self.redis.incrby(f"{PREFIX}{link_id}", count)
