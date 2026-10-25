"""Pure helpers of the insights: zero-filled day series and the marks histogram."""

import datetime as dt
from collections.abc import Mapping

from app.interfaces.http.v1.admin_insights.schemas import DayCount

DAYS = 14
MARK_VALUES = (2, 3, 4, 5)


def fill_days(
    counts: Mapping[dt.date, int], today: dt.date, days: int = DAYS
) -> list[DayCount]:
    """One entry per day, oldest first, ending today; missing days count 0."""
    start = today - dt.timedelta(days=days - 1)
    return [
        DayCount(date=day, count=counts.get(day, 0))
        for day in (start + dt.timedelta(days=i) for i in range(days))
    ]


def mark_histogram(counts: Mapping[int, int]) -> dict[str, int]:
    """Counts for 2, 3, 4 and 5 (keys are strings, as JSON object keys are)."""
    return {str(value): counts.get(value, 0) for value in MARK_VALUES}
