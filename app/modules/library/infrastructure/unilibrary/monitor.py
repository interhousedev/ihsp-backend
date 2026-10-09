"""Read side of the UniLibrary connection state, for the admin status page."""

from app.modules.library.infrastructure.unilibrary.breaker import CircuitBreaker
from app.modules.library.infrastructure.unilibrary.cache import StaleCache
from app.modules.library.infrastructure.unilibrary.call_log import CallLog
from app.modules.library.ports.external_monitor import (
    BreakerStatus,
    CacheStatsView,
    CallRecord,
)


class RedisExternalMonitor:
    """The breaker, the call log and the cache counters behind one object."""

    def __init__(
        self, breaker: CircuitBreaker, calls: CallLog, cache: StaleCache
    ) -> None:
        """Compose the three Redis-backed parts."""
        self._breaker = breaker
        self._calls = calls
        self._cache = cache

    async def breaker(self) -> BreakerStatus:
        """Breaker state now."""
        return await self._breaker.status()

    async def last_calls(self, limit: int) -> list[CallRecord]:
        """The most recent calls, newest first."""
        return await self._calls.recent(limit)

    async def cache_stats(self) -> CacheStatsView:
        """Hits, misses and stale answers."""
        return await self._cache.stats()
