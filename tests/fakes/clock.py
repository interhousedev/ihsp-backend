"""A clock whose time only moves when the test says so."""

from datetime import UTC, datetime, timedelta


class FixedClock:
    """Fixed UTC time with advance()."""

    def __init__(self, now: datetime | None = None) -> None:
        """Start at the given moment (default 2026-10-06 09:00 UTC)."""
        self._now = now or datetime(2026, 10, 6, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        """Return the current fixed moment."""
        return self._now

    def set(self, value: datetime) -> None:
        """Jump to a moment."""
        self._now = value

    def advance(self, **timedelta_kwargs: float) -> datetime:
        """Move forward, e.g. advance(hours=24); return the new time."""
        self._now += timedelta(**timedelta_kwargs)
        return self._now
