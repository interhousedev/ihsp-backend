"""LIB-16: the statistics window and the queue figures."""

from datetime import date

from app.modules.library.domain.taxonomy_errors import StatsRangeError
from app.modules.library.domain.taxonomy_stats import (
    MAX_RANGE_DAYS,
    days_between,
    resolve_range,
)

import pytest

TODAY = date(2026, 10, 6)


def test_default_window_is_the_last_30_days_including_today() -> None:
    """LIB-16: no dates means the last month."""
    assert resolve_range(TODAY, None, None) == (date(2026, 9, 7), TODAY)


def test_only_a_start_runs_to_today_and_only_an_end_goes_30_days_back() -> None:
    """LIB-16: each missing bound has a default."""
    assert resolve_range(TODAY, date(2026, 10, 1), None) == (date(2026, 10, 1), TODAY)
    assert resolve_range(TODAY, None, date(2026, 8, 31)) == (
        date(2026, 8, 2),
        date(2026, 8, 31),
    )


def test_start_after_end_is_refused() -> None:
    """LIB-16: an inverted window is an error."""
    with pytest.raises(StatsRangeError):
        resolve_range(TODAY, date(2026, 10, 5), date(2026, 10, 1))


def test_window_is_limited_to_one_year() -> None:
    """LIB-16: the dashboard never aggregates more than 366 days."""
    start = date(2025, 10, 6)

    assert resolve_range(TODAY, start, TODAY)[0] == start
    with pytest.raises(StatsRangeError):
        resolve_range(TODAY, date(2025, 10, 5), TODAY)
    assert MAX_RANGE_DAYS == 366


def test_days_between_lists_every_day_inclusive() -> None:
    """LIB-16: the uploads chart has a point for each day, also the empty ones."""
    assert days_between(date(2026, 10, 4), date(2026, 10, 6)) == [
        date(2026, 10, 4),
        date(2026, 10, 5),
        date(2026, 10, 6),
    ]
