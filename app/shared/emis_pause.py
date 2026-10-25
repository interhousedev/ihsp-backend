"""The EMIS pause: one Redis key that holds every EMIS call while EMIS asks for rest.

EMIS answers 429 (or a 5xx with Retry-After) when we ask too fast. The identity process
that got that answer stores the time the pause ends; every process reads it before it
calls EMIS, so a burst cannot keep knocking on a closed door for hours.
"""

import time
from collections.abc import Callable

from app.shared.redis_util import text, wait

from redis.asyncio import Redis

PAUSE_KEY = "emis:pause"


class EmisPause:
    """The shared pause, as the wall-clock second it ends at."""

    def __init__(self, redis: Redis, *, now: Callable[[], float] = time.time) -> None:
        """Keep the Redis client and the clock."""
        self.redis = redis
        self._now = now

    async def remaining(self) -> float:
        """Seconds until EMIS may be called again; 0.0 when there is no pause."""
        value = await wait(self.redis.get(PAUSE_KEY))
        if value is None:
            return 0.0
        try:
            until = float(text(value))
        except ValueError:
            return 0.0
        return max(0.0, until - self._now())

    async def pause(self, seconds: float) -> None:
        """Hold every EMIS call for ``seconds``; a longer pause already set is kept."""
        if await self.remaining() >= seconds:
            return
        until = self._now() + seconds
        await wait(self.redis.set(PAUSE_KEY, repr(until), ex=max(1, int(seconds) + 1)))
