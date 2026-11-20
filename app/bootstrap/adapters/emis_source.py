"""Choice of the EmisSource: the identity gateway in process, or over HTTP.

Both choices are wrapped in the profile cache (Redis plus an in-process LFU).
"""

from collections.abc import Awaitable, Callable

from app.bootstrap.adapters.emis_profile_cache import CachedEmisSource
from app.bootstrap.adapters.http_emis_source import HttpEmisSource
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisSource

from redis.asyncio import Redis

Closer = Callable[[], Awaitable[None]]


def make_emis_source(
    settings: Settings,
    *,
    gateway: EmisSource | None,
    in_process: bool,
    redis: Redis,
    clock: Clock,
) -> tuple[EmisSource, Closer | None]:
    """Return the in-process gateway (processes `all`, `identity`) or HttpEmisSource.

    `HttpEmisSource` calls `/internal/emis/*` of the identity process with the
    service token (processes `api`, `bot`, `worker`); it never sees Vault.
    """
    if in_process:
        if gateway is None:
            raise ValueError("the in-process EMIS source needs the identity EMIS part")
        return _cached(settings, gateway, redis, clock), None
    source = HttpEmisSource.from_settings(settings)
    return _cached(settings, source, redis, clock), source.aclose


def _cached(
    settings: Settings, source: EmisSource, redis: Redis, clock: Clock
) -> CachedEmisSource:
    return CachedEmisSource(
        source,
        redis=redis,
        clock=clock,
        ttl_seconds=settings.emis.cache_ttl_seconds,
        maxsize=settings.emis.cache_maxsize,
    )
