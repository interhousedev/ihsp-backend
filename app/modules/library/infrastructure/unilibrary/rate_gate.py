"""Our own request budget towards UniLibrary: N a second, K in flight (doc 3.3).

The per-second count is a Redis fixed window shared by every process; the number in
flight is a semaphore of this process.
"""

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from app.shared.redis_util import wait
from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.shared.clock import Clock

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]
MAX_WAITS = 5


class RateGate:
    """Hands out request slots; waits when the budget of the window is spent."""

    def __init__(
        self,
        *,
        redis: Redis,
        clock: Clock,
        rps: float,
        concurrency: int,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        """Set the budget: `rps` requests per second, `concurrency` in flight."""
        self.redis = redis
        self.clock = clock
        self.sleep = sleep
        self.window = max(1, math.ceil(1 / rps)) if rps > 0 else 1
        self.limit = max(1, int(rps * self.window))
        self._semaphore = asyncio.Semaphore(max(concurrency, 1))

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold a slot for one request; raises `UpstreamError('busy')` if none frees."""
        async with self._semaphore:
            await self._take()
            yield

    async def _take(self) -> None:
        for _ in range(MAX_WAITS):
            now = self.clock.now().timestamp()
            key = f"library:ext:rps:{int(now // self.window)}"
            try:
                count = await wait(self.redis.incr(key))
                if count == 1:
                    await self.redis.expire(key, self.window * 2)
            except RedisError:
                # Redis is down: the budget cannot be counted, so do not block.
                log.warning("library_unilibrary_rps_unavailable")
                return
            if count <= self.limit:
                return
            await self.sleep(self.window - (now % self.window))
        raise UpstreamError("busy", detail="request budget stayed full")
