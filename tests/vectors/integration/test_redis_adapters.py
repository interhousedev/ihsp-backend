"""NB-14: Redis cache of question vectors and the daily token counter."""

from app.modules.vectors.infrastructure.redis_query_cache import RedisQueryCache
from app.modules.vectors.infrastructure.redis_token_budget import RedisTokenBudget
from tests.fakes.clock import FixedClock

from fakeredis.aioredis import FakeRedis


async def test_a_cached_vector_comes_back_in_half_precision(redis: FakeRedis) -> None:
    """A miss is None; a hit is the vector (rounded to 2 bytes per number)."""
    cache = RedisQueryCache(redis)

    assert await cache.get("k") is None
    await cache.put("k", [0.5, -0.25, 1.0], 60)
    got = await cache.get("k")

    assert got == [0.5, -0.25, 1.0]
    assert 0 < await redis.ttl("k") <= 60


async def test_the_budget_counts_tokens_per_day(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """Tokens left fall as calls are billed; tomorrow starts fresh."""
    budget = RedisTokenBudget(redis, clock, 1000)

    assert await budget.remaining() == 1000
    await budget.spend(300)
    await budget.spend(0)
    assert await budget.remaining() == 700
    await budget.spend(5000)
    assert await budget.remaining() == 0

    clock.advance(hours=24)
    assert await budget.remaining() == 1000


async def test_a_limit_of_zero_means_no_limit(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """`VECTORS__DAILY_TOKEN_BUDGET=0` switches the cap off."""
    budget = RedisTokenBudget(redis, clock, 0)
    await budget.spend(10**9)

    assert await budget.remaining() is None
