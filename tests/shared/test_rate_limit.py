"""Redis fixed-window rate limiter."""

from app.shared.base_error import RateLimitedError
from app.shared.rate_limit import RateLimiter

import pytest
from redis.asyncio import Redis


async def test_hits_up_to_the_limit_pass_and_the_next_one_raises(
    redis: Redis,
) -> None:
    """ID-14: 3 hits with limit 3 are fine, the 4th is rejected with retry_after."""
    limiter = RateLimiter(redis)

    counts = [await limiter.hit("otp:1", limit=3, window_seconds=60) for _ in range(3)]
    with pytest.raises(RateLimitedError) as caught:
        await limiter.hit("otp:1", limit=3, window_seconds=60)

    assert counts == [1, 2, 3]
    assert 1 <= caught.value.params["retry_after"] <= 60


async def test_keys_are_counted_separately(redis: Redis) -> None:
    """One user's hits do not block another's."""
    limiter = RateLimiter(redis)
    await limiter.hit("a", limit=1, window_seconds=60)

    assert await limiter.hit("b", limit=1, window_seconds=60) == 1


async def test_reset_forgets_the_counter(redis: Redis) -> None:
    """A successful login clears the failure counter."""
    limiter = RateLimiter(redis)
    await limiter.hit("login", limit=1, window_seconds=60)

    await limiter.reset("login")

    assert await limiter.hit("login", limit=1, window_seconds=60) == 1


async def test_the_window_expires(redis: Redis) -> None:
    """The counter has a TTL, so the window is fixed."""
    limiter = RateLimiter(redis)

    await limiter.hit("w", limit=5, window_seconds=30)

    assert 0 < await redis.ttl("rl:w") <= 30
