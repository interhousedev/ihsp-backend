"""LIB-12: a Redis outage never breaks the library; UniLibrary just goes uncached."""

from collections.abc import Callable, Coroutine
from typing import Any, cast

from app.modules.library.infrastructure.unilibrary.breaker import CircuitBreaker
from app.modules.library.infrastructure.unilibrary.cache import StaleCache
from app.modules.library.infrastructure.unilibrary.call_log import CallLog
from app.modules.library.infrastructure.unilibrary.factory import build_unilibrary
from app.modules.library.infrastructure.unilibrary.rate_gate import RateGate
from app.modules.library.infrastructure.unilibrary.settings_store import (
    RedisExternalSettings,
)
from app.modules.library.ports.external_catalog import ExternalSearch
from app.modules.library.ports.external_monitor import BreakerState
from app.modules.library.ports.external_settings import FlagsOverride
from app.settings import LibrarySettings
from tests.fakes.clock import FixedClock
from tests.library.external.conftest import LIST_PATH
from tests.library.external.support import load

import respx
from redis.asyncio import Redis
from redis.exceptions import RedisError


class DownRedis:
    """Every command fails like a lost connection."""

    def __getattr__(self, name: str) -> Callable[..., Coroutine[Any, Any, None]]:
        """Any Redis method: an awaitable that raises."""

        async def fail(*_args: object, **_kwargs: object) -> None:
            raise RedisError(f"{name}: connection lost")

        return fail


def down() -> Redis:
    """A Redis client that is down."""
    return cast(Redis, DownRedis())


async def test_cache_misses_and_ignores_writes(clock: FixedClock) -> None:
    """LIB-12: no cache is a miss, not an error."""
    cache = StaleCache(down(), clock, stale_ttl=100)

    assert await cache.get("k", fresh_ttl=10) is None
    await cache.put("k", "body", fresh_ttl=10)
    await cache.count_hit()
    assert (await cache.stats()).hits == 0


async def test_breaker_stays_closed(clock: FixedClock) -> None:
    """LIB-12: when the state cannot be read, calls are allowed."""
    breaker = CircuitBreaker(down(), clock, failures=3, seconds=60)

    await breaker.record_failure()
    await breaker.record_success()

    assert (await breaker.status()).state is BreakerState.CLOSED


async def test_settings_fall_back_to_the_environment() -> None:
    """LIB-12: the override is empty, so the environment decides (off)."""
    assert await RedisExternalSettings(down()).override() == FlagsOverride()


async def test_call_log_is_empty(clock: FixedClock) -> None:
    """LIB-12: the status page shows nothing rather than failing."""
    log = CallLog(down(), clock)

    await log.record(ok=True, ms=3, path="/x")

    assert await log.recent(5) == []


async def test_request_budget_does_not_block(clock: FixedClock) -> None:
    """LIB-12: without a counter the gate lets the request through."""
    gate = RateGate(redis=down(), clock=clock, rps=1.0, concurrency=1)

    async with gate.slot():
        pass


async def test_search_still_works_without_redis(
    clock: FixedClock, upstream: respx.MockRouter
) -> None:
    """LIB-12: UniLibrary answers; only the cache and the counters are lost."""
    upstream.get(LIST_PATH).respond(200, json=load("list_page"))
    stack = build_unilibrary(LibrarySettings(unilibrary_enabled=True), down(), clock)

    page = await stack.catalog.search(ExternalSearch(q="fizika"))
    await stack.aclose()

    assert [r.external_id for r in page.records] == ["355186", "896986"]
