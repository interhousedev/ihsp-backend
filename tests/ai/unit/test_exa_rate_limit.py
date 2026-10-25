"""The Exa allowance shared by all processes: searches a second, in flight, cool-downs.

Redis is fakeredis (two clients on one server stand for two processes); the clock is a
fake one, and `sleep` moves it forward, so the waits are exact and the tests are quick.
"""

from typing import Any

from app.modules.ai.infrastructure.exa import ExaCallError
from app.modules.ai.infrastructure.exa_rate_limit import (
    BUCKET_KEY,
    INFLIGHT_KEY,
    ExaRateLimiter,
    LimitedExa,
)
from app.settings import ExaSettings

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis


class FakeTime:
    """A clock that `sleep` moves on."""

    def __init__(self, start: float = 1_000.0) -> None:
        """Start at `start` seconds."""
        self.current = start
        self.slept: list[float] = []

    def now(self) -> float:
        """The current time."""
        return self.current

    async def sleep(self, seconds: float) -> None:
        """Wait by moving the clock on."""
        self.slept.append(seconds)
        self.current += seconds


def limiter_pair(clock: FakeTime) -> tuple[ExaRateLimiter, ExaRateLimiter]:
    """Two limiters on one Redis server: two processes."""
    server = FakeServer()
    first = FakeRedis(server=server, decode_responses=True)
    second = FakeRedis(server=server, decode_responses=True)
    return (
        ExaRateLimiter(first, now=clock.now, sleep=clock.sleep),
        ExaRateLimiter(second, now=clock.now, sleep=clock.sleep),
    )


async def take(
    limiter: ExaRateLimiter,
    *,
    qps: int = 10,
    concurrent: int = 10,
    timeout: float = 5.0,
    lease: float = 35.0,
) -> str | None:
    """One acquire with the given limits."""
    return await limiter.acquire(
        max_qps=qps,
        max_concurrent=concurrent,
        timeout_seconds=timeout,
        lease_seconds=lease,
    )


async def test_the_tokens_are_shared_by_every_process() -> None:
    clock = FakeTime()
    first, second = limiter_pair(clock)

    assert await take(first, qps=2)
    assert await take(second, qps=2)  # the other process takes the second token
    assert clock.slept == []

    assert await take(first, qps=2)  # the third waits for a refill: 0.5 s at 2 a second
    assert sum(clock.slept) == pytest.approx(0.5)


async def test_a_wait_longer_than_the_queue_timeout_gives_up() -> None:
    clock = FakeTime()
    first, _ = limiter_pair(clock)
    assert await take(first, qps=1)

    assert await take(first, qps=1, timeout=0.2) is None
    assert clock.slept == []  # it did not even sleep: the wait is too long


async def test_at_most_max_concurrent_searches_are_in_flight() -> None:
    clock = FakeTime()
    first, second = limiter_pair(clock)
    lease = await take(first, qps=100, concurrent=1)
    assert lease

    assert await take(second, qps=100, concurrent=1, timeout=0) is None

    await first.release(lease)
    assert await take(second, qps=100, concurrent=1, timeout=0)


async def test_a_lease_that_is_never_released_expires_and_frees_its_slot() -> None:
    clock = FakeTime()
    first, second = limiter_pair(clock)
    assert await take(first, qps=100, concurrent=1, lease=5)

    clock.current += 6  # the process died: its lease is past its end
    assert await take(second, qps=100, concurrent=1, timeout=0)


async def test_a_cool_down_holds_every_process_for_the_seconds_exa_asked() -> None:
    clock = FakeTime()
    first, second = limiter_pair(clock)
    await first.cool_down(3)

    assert await take(second, timeout=1) is None
    assert await take(second, timeout=5)
    assert clock.slept and sum(clock.slept) == pytest.approx(3.0, abs=0.3)


async def test_the_state_is_kept_in_redis_under_the_documented_keys() -> None:
    clock = FakeTime()
    first, _ = limiter_pair(clock)
    lease = await take(first, qps=10, concurrent=10)

    assert await first.redis.zcard(INFLIGHT_KEY) == 1
    assert await first.redis.hget(BUCKET_KEY, "tokens") is not None
    await first.release(lease)
    assert await first.redis.zcard(INFLIGHT_KEY) == 0


class ScriptedClient:
    """Answers with the given status (or a body) and counts the calls."""

    def __init__(self, error: ExaCallError | None = None) -> None:
        """Keep the error to raise, if any."""
        self.error = error
        self.calls = 0

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Count the call and answer."""
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {"results": []}


async def test_a_full_local_queue_is_a_busy_answer_without_calling_exa() -> None:
    clock = FakeTime()
    first, _ = limiter_pair(clock)
    settings = ExaSettings(max_qps=1, queue_timeout_seconds=0)
    client = ScriptedClient()
    wrapped = LimitedExa(client, first, settings)
    assert await take(first, qps=1)  # the only token of the second is taken

    with pytest.raises(ExaCallError) as raised:
        await wrapped.search({"query": "x"})

    assert raised.value.status == 429
    assert client.calls == 0


async def test_a_429_from_exa_sets_the_cool_down_and_frees_the_slot() -> None:
    clock = FakeTime()
    first, second = limiter_pair(clock)
    settings = ExaSettings(max_qps=100, max_concurrent=1, queue_timeout_seconds=1)
    client = ScriptedClient(ExaCallError(status=429, retry_after=4.0))
    wrapped = LimitedExa(client, first, settings)

    with pytest.raises(ExaCallError):
        await wrapped.search({"query": "x"})

    assert await first.redis.zcard(INFLIGHT_KEY) == 0  # the slot is free again
    assert await take(second, timeout=1) is None  # every process waits for Exa


async def test_a_successful_search_releases_its_slot() -> None:
    clock = FakeTime()
    first, _ = limiter_pair(clock)
    settings = ExaSettings(max_qps=100, max_concurrent=1)
    wrapped = LimitedExa(ScriptedClient(), first, settings)

    assert await wrapped.search({"query": "x"}) == {"results": []}
    assert await first.redis.zcard(INFLIGHT_KEY) == 0
