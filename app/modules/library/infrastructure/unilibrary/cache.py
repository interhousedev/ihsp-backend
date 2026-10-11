"""Redis cache with stale-if-error for UniLibrary answers (doc 3.3).

An entry is a hash `{at, body}` that lives `fresh + stale` seconds in Redis. Fresh
or not is decided with the injected clock, so tests do not wait. A Redis outage is
a miss, never an error.
"""

from dataclasses import dataclass

from app.modules.library.ports.external_monitor import CacheStatsView
from app.shared.clock import Clock
from app.shared.redis_util import wait

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

STATS_KEY = "library:ext:cache_stats"


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A cached body and whether it is still inside its fresh time."""

    body: str
    fresh: bool


class StaleCache:
    """Fresh for a TTL, then kept `stale_ttl` seconds more for when the source fails."""

    def __init__(self, redis: Redis, clock: Clock, *, stale_ttl: int) -> None:
        """Store the client, the clock and how long expired answers are kept."""
        self.redis = redis
        self.clock = clock
        self.stale_ttl = stale_ttl

    async def get(self, key: str, *, fresh_ttl: int) -> CacheEntry | None:
        """The entry (fresh or stale) or None."""
        try:
            data = await wait(self.redis.hgetall(key))
        except RedisError:
            log.warning("library_unilibrary_cache_unavailable")
            return None
        if not data or "body" not in data:
            return None
        age = self.clock.now().timestamp() - float(data.get("at", 0))
        return CacheEntry(body=str(data["body"]), fresh=age < fresh_ttl)

    async def put(self, key: str, body: str, *, fresh_ttl: int) -> None:
        """Store the answer; it is kept for the fresh time plus the stale time."""
        at = str(self.clock.now().timestamp())
        try:
            await wait(self.redis.hset(key, mapping={"at": at, "body": body}))
            await self.redis.expire(key, fresh_ttl + self.stale_ttl)
        except RedisError:
            log.warning("library_unilibrary_cache_unavailable")

    async def count_hit(self) -> None:
        """A request answered from a fresh entry."""
        await self._count("hits")

    async def count_miss(self) -> None:
        """A request that needed the source."""
        await self._count("misses")

    async def count_stale(self) -> None:
        """A request answered from an expired entry because the source failed."""
        await self._count("stale_served")

    async def stats(self) -> CacheStatsView:
        """The counters."""
        try:
            data = await wait(self.redis.hgetall(STATS_KEY))
        except RedisError:
            return CacheStatsView()
        return CacheStatsView(
            hits=int(data.get("hits", 0)),
            misses=int(data.get("misses", 0)),
            stale_served=int(data.get("stale_served", 0)),
        )

    async def _count(self, field: str) -> None:
        try:
            await wait(self.redis.hincrby(STATS_KEY, field, 1))
        except RedisError:
            log.warning("library_unilibrary_cache_unavailable")
