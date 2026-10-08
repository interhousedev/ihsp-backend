"""Redis fixed-window rate limiter."""

from app.shared.base_error import RateLimitedError

from redis.asyncio import Redis


class RateLimiter:
    """Counts hits per key in a fixed time window."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Count one hit; raise RateLimitedError when over the limit."""
        full_key = f"rl:{key}"
        count = int(await self.redis.incr(full_key))
        if count == 1:
            await self.redis.expire(full_key, window_seconds)
        if count > limit:
            ttl = int(await self.redis.ttl(full_key))
            raise RateLimitedError(params={"retry_after": max(ttl, 1)})
        return count

    async def reset(self, key: str) -> None:
        """Forget the counter (e.g. after a successful login)."""
        await self.redis.delete(f"rl:{key}")
