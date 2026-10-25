"""Redis cache of rendered room pages (`room:{slug}:{date}`, 10 minutes)."""

from datetime import date

from redis.asyncio import Redis

TTL_SECONDS = 600


def _key(slug: str, day: date) -> str:
    return f"room:{slug}:{day.isoformat()}"


class RedisRoomPageCache:
    """Stores the HTML of a room day without its PIN."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def get(self, slug: str, day: date) -> str | None:
        """Return the cached HTML or None."""
        value = await self.redis.get(_key(slug, day))
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def put(self, slug: str, day: date, html: str) -> None:
        """Cache the HTML for ten minutes."""
        await self.redis.set(_key(slug, day), html, ex=TTL_SECONDS)

    async def invalidate(self, slug: str, day: date) -> None:
        """Forget the cached page of the room day."""
        await self.redis.delete(_key(slug, day))
