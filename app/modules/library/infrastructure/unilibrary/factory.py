"""Builds the UniLibrary connection: client, cache, breaker, catalog, monitor."""

import asyncio
from dataclasses import dataclass

from app.modules.library.infrastructure.unilibrary.breaker import CircuitBreaker
from app.modules.library.infrastructure.unilibrary.cache import StaleCache
from app.modules.library.infrastructure.unilibrary.call_log import CallLog
from app.modules.library.infrastructure.unilibrary.catalog import CachedCatalog
from app.modules.library.infrastructure.unilibrary.client import (
    UniLibraryClient,
    make_http_client,
)
from app.modules.library.infrastructure.unilibrary.monitor import RedisExternalMonitor
from app.modules.library.infrastructure.unilibrary.rate_gate import RateGate, Sleep
from app.modules.library.infrastructure.unilibrary.settings_store import (
    RedisExternalSettings,
)
from app.settings import LibrarySettings
from app.shared.clock import Clock

import httpx
from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class UniLibraryStack:
    """Everything of the UniLibrary connection; `aclose()` releases the pool."""

    client: UniLibraryClient
    cache: StaleCache
    breaker: CircuitBreaker
    catalog: CachedCatalog
    monitor: RedisExternalMonitor
    flags: RedisExternalSettings

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self.client.aclose()


def build_unilibrary(
    settings: LibrarySettings,
    redis: Redis,
    clock: Clock,
    *,
    http: httpx.AsyncClient | None = None,
    sleep: Sleep = asyncio.sleep,
) -> UniLibraryStack:
    """Wire the connection; no request is made until a catalogue method is called."""
    cache = StaleCache(redis, clock, stale_ttl=settings.unilibrary_stale_ttl)
    breaker = CircuitBreaker(
        redis,
        clock,
        failures=settings.unilibrary_breaker_failures,
        seconds=settings.unilibrary_breaker_seconds,
    )
    calls = CallLog(redis, clock)
    gate = RateGate(
        redis=redis,
        clock=clock,
        rps=settings.unilibrary_rps,
        concurrency=settings.unilibrary_concurrency,
        sleep=sleep,
    )
    client = UniLibraryClient(
        http=http or make_http_client(settings),
        gate=gate,
        calls=calls,
        settings=settings,
        clock=clock,
    )
    return UniLibraryStack(
        client=client,
        cache=cache,
        breaker=breaker,
        catalog=CachedCatalog(
            client=client, cache=cache, breaker=breaker, settings=settings
        ),
        monitor=RedisExternalMonitor(breaker, calls, cache),
        flags=RedisExternalSettings(redis),
    )
