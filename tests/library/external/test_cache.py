"""LIB-12: Redis cache that keeps an expired answer for when the source is down."""

from app.modules.library.infrastructure.unilibrary.cache import StaleCache
from tests.fakes.clock import FixedClock

import pytest
from fakeredis.aioredis import FakeRedis

FRESH = 600
STALE = 604_800


@pytest.fixture
def cache(redis: FakeRedis, clock: FixedClock) -> StaleCache:
    """A cache with the default stale time (7 days)."""
    return StaleCache(redis, clock, stale_ttl=STALE)


async def test_an_unknown_key_is_a_miss(cache: StaleCache) -> None:
    """LIB-12: nothing stored."""
    assert await cache.get("library:ext:list:x", fresh_ttl=FRESH) is None


async def test_a_stored_answer_is_fresh_until_its_ttl(
    cache: StaleCache, clock: FixedClock
) -> None:
    """LIB-12: list answers are fresh for 10 minutes."""
    await cache.put("library:ext:list:x", '{"a":1}', fresh_ttl=FRESH)

    clock.advance(seconds=FRESH - 1)
    entry = await cache.get("library:ext:list:x", fresh_ttl=FRESH)

    assert entry is not None
    assert entry.body == '{"a":1}'
    assert entry.fresh


async def test_an_expired_answer_is_still_returned_as_stale(
    cache: StaleCache, clock: FixedClock
) -> None:
    """LIB-12: stale-if-error needs the old answer."""
    await cache.put("library:ext:list:x", "body", fresh_ttl=FRESH)

    clock.advance(seconds=FRESH)
    entry = await cache.get("library:ext:list:x", fresh_ttl=FRESH)

    assert entry is not None
    assert entry.body == "body"
    assert not entry.fresh


async def test_redis_keeps_the_answer_for_fresh_plus_stale_time(
    cache: StaleCache, redis: FakeRedis
) -> None:
    """LIB-12: up to 7 days stale, so Redis expires the key after both."""
    await cache.put("library:ext:list:x", "body", fresh_ttl=FRESH)

    ttl = await redis.ttl("library:ext:list:x")

    assert FRESH + STALE - 5 <= ttl <= FRESH + STALE


async def test_a_new_answer_replaces_the_old_one(
    cache: StaleCache, clock: FixedClock
) -> None:
    """LIB-12: a refresh makes the entry fresh again."""
    await cache.put("library:ext:list:x", "old", fresh_ttl=FRESH)
    clock.advance(seconds=FRESH * 2)

    await cache.put("library:ext:list:x", "new", fresh_ttl=FRESH)

    entry = await cache.get("library:ext:list:x", fresh_ttl=FRESH)
    assert entry is not None and entry.body == "new" and entry.fresh


async def test_counters_feed_the_status_page(cache: StaleCache) -> None:
    """LIB-12: hits, misses and stale answers are counted."""
    await cache.count_hit()
    await cache.count_hit()
    await cache.count_miss()
    await cache.count_stale()

    stats = await cache.stats()

    assert (stats.hits, stats.misses, stats.stale_served) == (2, 1, 1)
