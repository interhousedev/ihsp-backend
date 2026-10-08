"""WEB-23: the daily counters in Redis (fakeredis): key, fields and 48 h TTL."""

from datetime import date

from app.modules.flashcards.domain.study import DailyUsage
from app.modules.flashcards.infrastructure.redis_daily_counters import (
    RedisDailyCounters,
)
from app.shared.ids import new_id

from fakeredis.aioredis import FakeRedis

DAY = date(2026, 10, 6)


async def test_nothing_studied_means_zero_counters(redis: FakeRedis) -> None:
    """A day without answers reads as 0 / 0."""
    counters = RedisDailyCounters(redis)

    usage = await counters.usage(new_id(), new_id(), DAY)

    assert usage == DailyUsage(new=0, review=0)


async def test_new_and_review_are_counted_in_one_hash_per_day(
    redis: FakeRedis,
) -> None:
    """Key `fc:day:{user}:{set}:{date}` has the fields `new` and `review`."""
    counters = RedisDailyCounters(redis)
    user, set_id = new_id(), new_id()

    await counters.increment(user, set_id, DAY, "new")
    await counters.increment(user, set_id, DAY, "new")
    await counters.increment(user, set_id, DAY, "review")

    assert await counters.usage(user, set_id, DAY) == DailyUsage(new=2, review=1)
    key = f"fc:day:{user}:{set_id}:2026-10-06"
    stored = await redis.hgetall(key)  # type: ignore[misc]
    assert stored == {"new": "2", "review": "1"}


async def test_the_counters_expire_after_48_hours(redis: FakeRedis) -> None:
    """README Redis keys: the TTL is 48 hours."""
    counters = RedisDailyCounters(redis)
    user, set_id = new_id(), new_id()

    await counters.increment(user, set_id, DAY, "new")

    ttl = await redis.ttl(f"fc:day:{user}:{set_id}:2026-10-06")
    assert 48 * 3600 - 5 <= ttl <= 48 * 3600


async def test_days_users_and_sets_are_counted_apart(redis: FakeRedis) -> None:
    """The limit is per user, per set and per day."""
    counters = RedisDailyCounters(redis)
    user, other, set_a, set_b = new_id(), new_id(), new_id(), new_id()

    await counters.increment(user, set_a, DAY, "new")

    assert (await counters.usage(user, set_a, DAY)).new == 1
    assert (await counters.usage(user, set_a, date(2026, 10, 7))).new == 0
    assert (await counters.usage(user, set_b, DAY)).new == 0
    assert (await counters.usage(other, set_a, DAY)).new == 0
