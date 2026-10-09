"""LIB-12: three failures in a row stop the calls for 60 seconds."""

from app.modules.library.infrastructure.unilibrary.breaker import CircuitBreaker
from app.modules.library.ports.external_monitor import BreakerState
from tests.fakes.clock import FixedClock

import pytest
from fakeredis.aioredis import FakeRedis

FAILURES = 3
SECONDS = 60


@pytest.fixture
def breaker(redis: FakeRedis, clock: FixedClock) -> CircuitBreaker:
    """A breaker with the default settings (3 failures, 60 seconds)."""
    return CircuitBreaker(redis, clock, failures=FAILURES, seconds=SECONDS)


async def test_it_starts_closed(breaker: CircuitBreaker) -> None:
    """LIB-12: nothing happened yet."""
    status = await breaker.status()

    assert status.state is BreakerState.CLOSED
    assert status.retry_after == 0


async def test_two_failures_leave_it_closed_and_the_third_opens_it(
    breaker: CircuitBreaker,
) -> None:
    """LIB-12: `unilibrary_breaker_failures` consecutive failures open it."""
    await breaker.record_failure()
    await breaker.record_failure()
    assert (await breaker.status()).state is BreakerState.CLOSED

    await breaker.record_failure()

    status = await breaker.status()
    assert status.state is BreakerState.OPEN
    assert status.is_open
    assert status.retry_after == SECONDS


async def test_a_success_resets_the_count(breaker: CircuitBreaker) -> None:
    """LIB-12: failures must be in a row."""
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.record_success()
    await breaker.record_failure()
    await breaker.record_failure()

    assert (await breaker.status()).state is BreakerState.CLOSED


async def test_retry_after_counts_down_with_the_clock(
    breaker: CircuitBreaker, clock: FixedClock
) -> None:
    """LIB-12: the error tells the caller how long to wait."""
    for _ in range(FAILURES):
        await breaker.record_failure()

    clock.advance(seconds=45)

    status = await breaker.status()
    assert status.state is BreakerState.OPEN
    assert status.retry_after == 15


async def test_after_the_open_time_one_probe_is_allowed(
    breaker: CircuitBreaker, clock: FixedClock
) -> None:
    """LIB-12: half-open lets the next call through to try."""
    for _ in range(FAILURES):
        await breaker.record_failure()

    clock.advance(seconds=SECONDS)

    assert (await breaker.status()).state is BreakerState.HALF_OPEN


async def test_a_failed_probe_opens_it_again_at_once(
    breaker: CircuitBreaker, clock: FixedClock
) -> None:
    """LIB-12: no new count of three after a failed probe."""
    for _ in range(FAILURES):
        await breaker.record_failure()
    clock.advance(seconds=SECONDS)

    await breaker.record_failure()

    status = await breaker.status()
    assert status.state is BreakerState.OPEN
    assert status.retry_after == SECONDS


async def test_a_good_probe_closes_it(
    breaker: CircuitBreaker, clock: FixedClock
) -> None:
    """LIB-12: back to normal."""
    for _ in range(FAILURES):
        await breaker.record_failure()
    clock.advance(seconds=SECONDS)

    await breaker.record_success()

    assert (await breaker.status()).state is BreakerState.CLOSED


async def test_retry_after_of_the_source_opens_it_at_once(
    breaker: CircuitBreaker,
) -> None:
    """LIB-12: `Retry-After: 120` is respected after a single failure."""
    await breaker.record_failure(retry_after=120)

    status = await breaker.status()
    assert status.state is BreakerState.OPEN
    assert status.retry_after == 120


async def test_retry_after_is_capped_at_an_hour(breaker: CircuitBreaker) -> None:
    """LIB-12: a silly header cannot switch the source off for days."""
    await breaker.record_failure(retry_after=999_999)

    assert (await breaker.status()).retry_after == 3600
