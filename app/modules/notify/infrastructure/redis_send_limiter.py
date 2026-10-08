"""Global send pacing: at most N messages per second over every worker."""

import asyncio
import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

DEFAULT_PER_SECOND = 25  # Telegram allows about 30 messages per second overall


class RedisSendLimiter:
    """Counts sends in one-second Redis windows; waits for the next when full."""

    def __init__(
        self,
        redis: Redis,
        *,
        per_second: int = DEFAULT_PER_SECOND,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Store Redis, the rate and the (injectable) wall clock and sleep."""
        self.redis = redis
        self.per_second = per_second
        self._now = now
        self._sleep = sleep

    async def acquire(self) -> None:
        """Return when one more message may be sent in the current second."""
        while True:
            second = int(self._now())
            key = f"tg:send:{second}"
            count = int(await self.redis.incr(key))
            if count == 1:
                await self.redis.expire(key, 3)
            if count <= self.per_second:
                return
            await self._sleep(max(second + 1 - self._now(), 0.01))
