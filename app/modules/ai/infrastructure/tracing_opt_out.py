"""`TracingOptOut` over the identity preferences, cached for a short while."""

import time
from collections.abc import Awaitable, Callable
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

OPT_OUT_TTL_SECONDS = 30.0
_MAX_ENTRIES = 10_000


class CachedTracingOptOut:
    """Implements `TracingOptOut`: one preference read per user per TTL.

    A failed read masks (True) and is cached too, so a broken directory does not
    turn every model call into a query.
    """

    def __init__(
        self,
        load: Callable[[UUID], Awaitable[bool]],
        *,
        ttl_seconds: float = OPT_OUT_TTL_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the loader, the time to live and the clock."""
        self._load = load
        self._ttl = ttl_seconds
        self._now = now
        self._cache: dict[UUID, tuple[float, bool]] = {}

    async def limits_tracing(self, user_id: UUID) -> bool:
        """The cached choice, read again once it is older than the TTL."""
        now = self._now()
        hit = self._cache.get(user_id)
        if hit is not None and hit[0] > now:
            return hit[1]
        try:
            value = await self._load(user_id)
        except Exception:
            log.warning("tracing_opt_out_read_failed", exc_info=True)
            value = True
        if len(self._cache) >= _MAX_ENTRIES:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        self._cache[user_id] = (now + self._ttl, value)
        return value
