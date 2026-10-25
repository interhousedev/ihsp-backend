"""Wrong room PIN attempts per room and IP (`rl:room-pin:{slug}:{ip}`)."""

from redis.asyncio import Redis

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


def _key(slug: str, ip: str | None) -> str:
    return f"rl:room-pin:{slug}:{ip or 'unknown'}"


class RedisPinLimiter:
    """Allows five wrong PINs per fifteen minutes (ROOM-5)."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def retry_after(self, slug: str, ip: str | None) -> int | None:
        """Return the seconds to wait once five wrong PINs were entered."""
        key = _key(slug, ip)
        count = await self.redis.get(key)
        if count is None or int(count) < MAX_FAILURES:
            return None
        return max(int(await self.redis.ttl(key)), 1)

    async def record_failure(self, slug: str, ip: str | None) -> None:
        """Count one wrong PIN and start the window on the first one."""
        key = _key(slug, ip)
        if int(await self.redis.incr(key)) == 1:
            await self.redis.expire(key, WINDOW_SECONDS)
