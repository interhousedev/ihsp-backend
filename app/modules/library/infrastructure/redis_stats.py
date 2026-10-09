"""Redis counters of opens and distinct readers (rolled up daily into `item_stats`).

Keys (all expire after three days, long enough for the 02:10 rollup to read them):
`library:stats:{YYYY-MM-DD}` hash with `{item_id}:opens` and `{item_id}:offline`
counters; `library:stats:readers:{YYYY-MM-DD}:{item_id}` set of user ids.
"""

from datetime import timedelta
from uuid import UUID

from app.modules.library.infrastructure.redis_util import wait
from app.shared.clock import Clock

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

KEY_TTL = timedelta(days=3)


def stats_key(day: str) -> str:
    """The hash of a day."""
    return f"library:stats:{day}"


def readers_key(day: str, item_id: UUID | str) -> str:
    """The set of distinct readers of an item on a day."""
    return f"library:stats:readers:{day}:{item_id}"


class RedisStatsRecorder:
    """Counts opens and offline saves; a Redis outage only logs."""

    def __init__(self, redis: Redis, clock: Clock) -> None:
        """Store the client and the clock."""
        self.redis = redis
        self.clock = clock

    def _day(self) -> str:
        return self.clock.now().date().isoformat()

    async def opened(self, item_id: UUID, user_id: UUID | None) -> None:
        """Count one open of the item and remember the reader."""
        day = self._day()
        try:
            await wait(self.redis.hincrby(stats_key(day), f"{item_id}:opens", 1))
            await self.redis.expire(stats_key(day), int(KEY_TTL.total_seconds()))
            if user_id is not None:
                await wait(self.redis.sadd(readers_key(day, item_id), str(user_id)))
                await self.redis.expire(
                    readers_key(day, item_id), int(KEY_TTL.total_seconds())
                )
        except RedisError:
            log.warning("library_stats_failed", item_id=str(item_id))

    async def offline_saved(self, item_id: UUID) -> None:
        """Count one 'saved for offline' of the item."""
        day = self._day()
        try:
            await wait(self.redis.hincrby(stats_key(day), f"{item_id}:offline", 1))
            await self.redis.expire(stats_key(day), int(KEY_TTL.total_seconds()))
        except RedisError:
            log.warning("library_stats_failed", item_id=str(item_id))
