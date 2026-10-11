"""Circuit breaker for UniLibrary (Redis `library:ext:breaker`, doc 3.3).

`failures` failures, timeouts or 403s in a row open it for `seconds`. While open,
nobody calls UniLibrary; the catalogue answers from the cache. When the time is
over the next call is a probe: success closes it, failure opens it again at once.
"""

import math

from app.shared.redis_util import wait
from app.modules.library.ports.external_monitor import BreakerState, BreakerStatus
from app.shared.clock import Clock

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

KEY = "library:ext:breaker"
MAX_HOLD_SECONDS = 3600  # a silly `Retry-After` cannot switch the source off for days
KEY_TTL_SECONDS = 86_400


class CircuitBreaker:
    """Counts failures and says whether calls may go out."""

    def __init__(
        self, redis: Redis, clock: Clock, *, failures: int, seconds: int
    ) -> None:
        """Open after `failures` in a row, for `seconds`."""
        self.redis = redis
        self.clock = clock
        self.failures = failures
        self.seconds = seconds

    async def status(self) -> BreakerStatus:
        """Closed, open (with the wait left) or half-open."""
        try:
            data = await wait(self.redis.hgetall(KEY))
        except RedisError:
            log.warning("library_unilibrary_breaker_unavailable")
            return BreakerStatus(BreakerState.CLOSED)
        failures = int(data.get("failures", 0))
        open_until = float(data.get("open_until", 0))
        now = self.clock.now().timestamp()
        if open_until > now:
            return BreakerStatus(
                BreakerState.OPEN, retry_after=math.ceil(open_until - now)
            )
        if failures >= self.failures:
            return BreakerStatus(BreakerState.HALF_OPEN)
        return BreakerStatus(BreakerState.CLOSED)

    async def record_success(self) -> None:
        """A good answer: forget the failures."""
        try:
            await self.redis.delete(KEY)
        except RedisError:
            log.warning("library_unilibrary_breaker_unavailable")

    async def record_failure(self, retry_after: int | None = None) -> None:
        """Count a failure; open the breaker when due or when the source asked."""
        try:
            count = await wait(self.redis.hincrby(KEY, "failures", 1))
            hold = self._hold(count, retry_after)
            if hold:
                now = self.clock.now().timestamp()
                await wait(self.redis.hset(KEY, "open_until", str(now + hold)))
            await self.redis.expire(KEY, KEY_TTL_SECONDS)
        except RedisError:
            log.warning("library_unilibrary_breaker_unavailable")

    def _hold(self, count: int, retry_after: int | None) -> int:
        if retry_after:
            return min(retry_after, MAX_HOLD_SECONDS)
        return self.seconds if count >= self.failures else 0
