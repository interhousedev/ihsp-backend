"""Port: what the administrator sees of the UniLibrary connection."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class BreakerState(StrEnum):
    """State of the circuit breaker (`UniLibraryStatus.breaker`)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"  # the open time is over; the next call is a probe


@dataclass(frozen=True, slots=True)
class BreakerStatus:
    """The breaker state and, while open, the seconds until the next probe."""

    state: BreakerState
    retry_after: int = 0

    @property
    def is_open(self) -> bool:
        """True while calls to UniLibrary are held back."""
        return self.state is BreakerState.OPEN


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One call to UniLibrary: when, whether it worked, how long, which path."""

    at: datetime
    ok: bool
    ms: int
    path: str


@dataclass(frozen=True, slots=True)
class CacheStatsView:
    """Cache counters since the last reset of Redis."""

    hits: int = 0
    misses: int = 0
    stale_served: int = 0


class ExternalMonitor(Protocol):
    """Read side of the connection state, for the admin status page."""

    async def breaker(self) -> BreakerStatus:
        """Breaker state now."""
        ...

    async def last_calls(self, limit: int) -> list[CallRecord]:
        """The most recent calls, newest first."""
        ...

    async def cache_stats(self) -> CacheStatsView:
        """Hits, misses and stale answers."""
        ...
