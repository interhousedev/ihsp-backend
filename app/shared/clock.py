"""Injected time source."""

from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

TASHKENT = ZoneInfo("Asia/Tashkent")


class Clock(Protocol):
    """Source of the current time (UTC, timezone-aware)."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        ...


class SystemClock:
    """Real clock."""

    def now(self) -> datetime:
        """Return datetime.now(UTC)."""  # noqa: D402
        return datetime.now(UTC)


def local_today(clock: Clock) -> date:
    """Return today's date in Tashkent."""
    return clock.now().astimezone(TASHKENT).date()


def to_local(value: datetime) -> datetime:
    """Convert an aware datetime to Tashkent time."""
    return value.astimezone(TASHKENT)
