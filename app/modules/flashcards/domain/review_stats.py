"""Review statistics of the deck overview: heatmap days, averages and streaks."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class DayCount:
    """Reviews finished on one study day (Tashkent calendar day)."""

    day: date
    count: int


@dataclass(frozen=True, slots=True)
class ReviewStats:
    """What the heatmap and the four numbers under it show."""

    year: int
    days: tuple[DayCount, ...]
    total_reviews: int
    days_studied: int
    daily_average: float
    days_learned_percent: float
    longest_streak: int
    current_streak: int
    first_review_date: date | None
    today_count: int
    today_seconds: int


def longest_streak(days: set[date]) -> int:
    """Return the longest run of consecutive study days."""
    best = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous == day - timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return best


def current_streak(days: set[date], today: date) -> int:
    """Return the run of study days that ends today, or yesterday if today is empty.

    A student who has not studied yet today keeps the streak until midnight.
    """
    cursor = today if today in days else today - timedelta(days=1)
    run = 0
    while cursor in days:
        run += 1
        cursor -= timedelta(days=1)
    return run


def _period_days(year: int, today: date, first: date | None) -> int:
    """Return the days of `year` from the first review (or Jan 1) up to today."""
    if first is None:
        return 0
    start = max(date(year, 1, 1), first)
    end = min(date(year, 12, 31), today)
    return max(0, (end - start).days + 1)


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def compute_stats(
    counts: Mapping[date, int], *, year: int, today: date, today_ms: int
) -> ReviewStats:
    """Build the statistics from per-day review counts of the whole history.

    The heatmap, the average and "days learned" cover `year`; the streaks look at
    the whole history, so a streak does not break on January 1.
    """
    studied = {day for day, count in counts.items() if count > 0}
    in_year = sorted(day for day in studied if day.year == year)
    total = sum(counts[day] for day in in_year)
    first = min(studied) if studied else None
    return ReviewStats(
        year=year,
        days=tuple(DayCount(day, counts[day]) for day in in_year),
        total_reviews=total,
        days_studied=len(in_year),
        daily_average=round(total / len(in_year), 1) if in_year else 0.0,
        days_learned_percent=_percent(len(in_year), _period_days(year, today, first)),
        longest_streak=longest_streak(studied),
        current_streak=current_streak(studied, today),
        first_review_date=first,
        today_count=counts.get(today, 0),
        today_seconds=(today_ms + 500) // 1000,
    )
