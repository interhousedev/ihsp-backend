"""LIB-12: at most N requests a second and K in flight go out to UniLibrary."""

import asyncio

from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.modules.library.infrastructure.unilibrary.rate_gate import RateGate
from tests.fakes.clock import FixedClock
from tests.library.external.conftest import Sleeper

import pytest
from fakeredis.aioredis import FakeRedis


def make_gate(
    redis: FakeRedis,
    clock: FixedClock,
    sleeper: Sleeper,
    *,
    rps: float = 3.0,
    concurrency: int = 2,
) -> RateGate:
    """A gate over fakeredis whose waits move the test clock."""
    return RateGate(
        redis=redis, clock=clock, rps=rps, concurrency=concurrency, sleep=sleeper
    )


async def test_requests_inside_the_budget_do_not_wait(
    redis: FakeRedis, clock: FixedClock, sleeper: Sleeper
) -> None:
    """LIB-12: three a second are fine at `rps=3`."""
    gate = make_gate(redis, clock, sleeper)

    for _ in range(3):
        async with gate.slot():
            pass

    assert sleeper.slept == []


async def test_requests_over_the_budget_wait_for_the_next_second(
    redis: FakeRedis, clock: FixedClock, sleeper: Sleeper
) -> None:
    """LIB-12: the fourth to seventh request of one second move to later seconds."""
    gate = make_gate(redis, clock, sleeper)
    started = clock.now()
    stamps = []

    for _ in range(7):
        async with gate.slot():
            stamps.append(int(clock.now().timestamp()))

    per_second = [stamps.count(second) for second in sorted(set(stamps))]
    assert max(per_second) <= 3
    assert len(sleeper.slept) == 2
    assert all(0 < seconds <= 1 for seconds in sleeper.slept)
    assert clock.now() > started


async def test_a_slow_rate_spreads_requests_over_longer_windows(
    redis: FakeRedis, clock: FixedClock, sleeper: Sleeper
) -> None:
    """LIB-12: `rps=0.5` allows one request every two seconds."""
    gate = make_gate(redis, clock, sleeper, rps=0.5)

    for _ in range(3):
        async with gate.slot():
            pass

    assert len(sleeper.slept) == 2


async def test_only_so_many_requests_are_in_flight(
    redis: FakeRedis, clock: FixedClock, sleeper: Sleeper
) -> None:
    """LIB-12: `concurrency=2` holds the third caller until a slot frees."""
    gate = RateGate(redis=redis, clock=clock, rps=1000.0, concurrency=2, sleep=sleeper)
    running = 0
    peak = 0

    async def work() -> None:
        nonlocal running, peak
        async with gate.slot():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(work() for _ in range(6)))

    assert peak == 2


async def test_a_budget_that_stays_full_gives_up_as_busy(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """LIB-12: waiting does not go on forever."""

    async def no_progress(_seconds: float) -> None:
        return None

    gate = RateGate(redis=redis, clock=clock, rps=1.0, concurrency=2, sleep=no_progress)
    async with gate.slot():
        pass

    with pytest.raises(UpstreamError) as caught:
        async with gate.slot():
            pass

    assert caught.value.kind == "busy"
