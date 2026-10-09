"""Reads the Redis counters that `RedisStatsRecorder` writes (rollup, no-result list).

Keys, all written by the catalogue and reader areas, read here:
- `library:stats:{YYYY-MM-DD}`: hash with `{item_id}:opens` and `{item_id}:offline`;
- `library:stats:readers:{YYYY-MM-DD}:{item_id}`: set of user ids (see `redis_stats`);
- `library:stats:noresult:{YYYY-MM-DD}`: hash `{normalised query} -> count` of
  searches that found nothing. Nothing writes it yet; the catalogue search should
  `HINCRBY` it and give the key a 35 day expiry.
"""

from datetime import date
from uuid import UUID

from app.modules.library.domain.taxonomy_stats import DayCounters
from app.modules.library.infrastructure.redis_stats import readers_key, stats_key
from app.modules.library.infrastructure.redis_util import wait

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

DELETE_CHUNK = 500


def no_result_key(day: str) -> str:
    """The hash of searches without results on a day."""
    return f"library:stats:noresult:{day}"


def _count(value: str) -> int:
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def _split(field: str) -> tuple[UUID, str] | None:
    """`{item_id}:{opens|offline}` as `(item id, counter name)`; junk gives None."""
    item_part, _, name = field.rpartition(":")
    try:
        return UUID(item_part), name
    except ValueError:
        return None


class RedisStatsCounters:
    """Reads and clears the daily counters of the library."""

    def __init__(self, redis: Redis) -> None:
        """Store the client."""
        self.redis = redis

    async def day(self, day: date) -> dict[UUID, DayCounters]:
        """Counters of every item that was opened or saved on the day."""
        stamp = day.isoformat()
        fields: dict[str, str] = await wait(self.redis.hgetall(stats_key(stamp)))
        opens: dict[UUID, int] = {}
        offline: dict[UUID, int] = {}
        for field, value in fields.items():
            parsed = _split(field)
            if parsed is None:
                continue
            item_id, name = parsed
            if name == "opens":
                opens[item_id] = _count(value)
            elif name == "offline":
                offline[item_id] = _count(value)
        counters: dict[UUID, DayCounters] = {}
        for item_id in opens.keys() | offline.keys():
            readers = await wait(self.redis.scard(readers_key(stamp, item_id)))
            counters[item_id] = DayCounters(
                opens=opens.get(item_id, 0),
                readers=int(readers),
                offline_saves=offline.get(item_id, 0),
            )
        return counters

    async def discard(self, day: date, item_ids: list[UUID]) -> None:
        """Delete the day's counters and reader sets of the items."""
        stamp = day.isoformat()
        await wait(self.redis.delete(stats_key(stamp)))
        for start in range(0, len(item_ids), DELETE_CHUNK):
            chunk = item_ids[start : start + DELETE_CHUNK]
            await wait(self.redis.delete(*(readers_key(stamp, i) for i in chunk)))

    async def no_results(self, day: date, limit: int) -> dict[str, int]:
        """The most frequent searches without results on the day, as `{query: count}`."""
        try:
            fields: dict[str, str] = await wait(
                self.redis.hgetall(no_result_key(day.isoformat()))
            )
        except RedisError:
            log.warning("library_noresult_unavailable", day=day.isoformat())
            return {}
        counts = {query: _count(value) for query, value in fields.items()}
        top = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
        return {query: count for query, count in top if count > 0}
