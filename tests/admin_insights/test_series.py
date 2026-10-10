"""Zero-filled day series and the marks histogram of the insights."""

import datetime as dt

from app.interfaces.http.v1.admin_insights.reader import local_midnight_days_ago
from app.interfaces.http.v1.admin_insights.series import fill_days, mark_histogram

TODAY = dt.date(2026, 10, 10)


def test_days_are_oldest_first_and_zero_filled() -> None:
    series = fill_days({TODAY: 4, dt.date(2026, 10, 8): 2}, TODAY, days=3)

    assert [(d.date.isoformat(), d.count) for d in series] == [
        ("2026-10-08", 2),
        ("2026-10-09", 0),
        ("2026-10-10", 4),
    ]


def test_the_default_window_is_fourteen_days() -> None:
    series = fill_days({}, TODAY)

    assert len(series) == 14
    assert series[0].date == dt.date(2026, 9, 27)


def test_histogram_has_every_mark_value() -> None:
    assert mark_histogram({5: 7, 3: 1}) == {"2": 0, "3": 1, "4": 0, "5": 7}


def test_window_starts_at_tashkent_midnight() -> None:
    now = dt.datetime(2026, 10, 10, 20, 0, tzinfo=dt.UTC)  # 01:00 on 11 Oct in Tashkent

    start = local_midnight_days_ago(now, 2)

    assert start.isoformat() == "2026-10-10T00:00:00+05:00"
