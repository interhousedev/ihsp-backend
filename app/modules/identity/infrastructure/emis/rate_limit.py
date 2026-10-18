"""The EMIS allowance shared by every process: calls a second, per bucket, in Redis.

Two buckets: ``api`` (EMIS__MAX_QPS, every EMIS request) and ``file``
(EMIS__FILE_MAX_QPS, material downloads). Each bucket keeps one counter per
wall-clock second (INCR, expiring after two seconds); a call past the limit of its
second waits for the next one. The counter is atomic, so two processes never both
take the last call of a second.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.shared.redis_util import wait

from redis.asyncio import Redis

KEY_PREFIX = "emis:rate"
MIN_WAIT_SECONDS = 0.001


class EmisRateLimiter:
    """Waits until the bucket has a call left this second; clock injectable."""

    def __init__(
        self,
        redis: Redis,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Keep the Redis client, the clock and the sleep."""
        self.redis = redis
        self._now = now
        self._sleep = sleep

    async def acquire(self, bucket: str, qps: int) -> None:
        """Return when one more call of ``bucket`` fits in this second."""
        while True:
            now = self._now()
            second = int(now)
            key = f"{KEY_PREFIX}:{bucket}:{second}"
            count = await wait(self.redis.incr(key))
            if count == 1:
                await wait(self.redis.expire(key, 2))
            if count <= qps:
                return
            await self._sleep(max(second + 1 - now, MIN_WAIT_SECONDS))
