"""Redis counter of the tokens the embedding calls spent today."""

from app.shared.clock import Clock

from redis.asyncio import Redis

DAY_SECONDS = 86_400
KEEP_SECONDS = 2 * DAY_SECONDS


class RedisTokenBudget:
    """One counter per UTC day; `daily_limit` 0 means no limit."""

    def __init__(self, redis: Redis, clock: Clock, daily_limit: int) -> None:
        """Keep the Redis client, the clock and the limit."""
        self.redis = redis
        self.clock = clock
        self.daily_limit = daily_limit

    def _key(self) -> str:
        return f"vectors:tokens:{self.clock.now().date().isoformat()}"

    async def remaining(self) -> int | None:
        """Tokens left for today; None when there is no limit."""
        if self.daily_limit <= 0:
            return None
        spent = int(await self.redis.get(self._key()) or 0)
        return max(0, self.daily_limit - spent)

    async def spend(self, tokens: int) -> None:
        """Add the tokens a call was billed."""
        if tokens <= 0:
            return
        key = self._key()
        await self.redis.incrby(key, tokens)
        await self.redis.expire(key, KEEP_SECONDS)
