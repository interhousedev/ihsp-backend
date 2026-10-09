"""Library statistics (LIB-16): the window and the figures the job rolls up."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.library.domain.taxonomy_errors import StatsRangeError

DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 366


@dataclass(frozen=True, slots=True)
class DayCounters:
    """What the Redis counters hold for one item on one day."""

    opens: int
    readers: int
    offline_saves: int


def resolve_range(
    today: date, start: date | None, end: date | None
) -> tuple[date, date]:
    """The inclusive window: the last 30 days by default, at most 366 days long."""
    last = end or today
    first = start or last - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if first > last or (last - first).days + 1 > MAX_RANGE_DAYS:
        raise StatsRangeError(
            params={"from": first.isoformat(), "to": last.isoformat()}
        )
    return first, last


def days_between(start: date, end: date) -> list[date]:
    """Every day from `start` to `end`, inclusive."""
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]
