"""The cooldown of a student's own EMIS refresh, in Redis."""

from uuid import UUID

from redis.asyncio import Redis


class RedisSyncCooldown:
    """One expiring key per student."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    async def take(self, user_id: UUID, seconds: int) -> int:
        """Start the cooldown and return 0, or return the seconds still to wait."""
        key = f"mcp:sync:cooldown:{user_id}"
        if await self._redis.set(key, "1", nx=True, ex=seconds):
            return 0
        return max(int(await self._redis.ttl(key)), 1)
