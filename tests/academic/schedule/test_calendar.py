"""Calendar logic: weekday of a date, week parity, bell times (ACA-4, ACA-7)."""

import datetime as dt

from app.modules.academic.domain.schedule.calendar import (
    bell_for,
    effective_weekday,
    lesson_times,
    monday_of,
    week_parity,
)
from app.modules.academic.domain.schedule.term import MovedDay
from tests.academic.schedule.builders import make_term

import pytest


def test_a_non_study_day_has_no_weekday() -> None:
    """ACA-4: no lessons on holidays."""
    term = make_term(non_study_days=[dt.date(2026, 10, 1)])

    assert effective_weekday(dt.date(2026, 10, 1), term) is None


def test_sunday_has_no_weekday_without_a_moved_day_rule() -> None:
    """ACA-4: Sunday is never a study day by itself."""
    assert effective_weekday(dt.date(2026, 10, 4), make_term()) is None


def test_a_moved_saturday_follows_monday() -> None:
    """ACA-4: 'Saturday 14.11 follows Monday' uses Monday's timetable."""
    term = make_term(
        moved_days=[MovedDay(date=dt.date(2026, 11, 14), follows_weekday=1)]
    )

    assert dt.date(2026, 11, 14).isoweekday() == 6
    assert effective_weekday(dt.date(2026, 11, 14), term) == 1


def test_a_moved_sunday_is_a_study_day() -> None:
    """ACA-4: a moved-day rule makes even a Sunday a study day."""
    term = make_term(
        moved_days=[MovedDay(date=dt.date(2026, 10, 4), follows_weekday=3)]
    )

    assert effective_weekday(dt.date(2026, 10, 4), term) == 3


def test_a_non_study_day_wins_over_a_moved_day() -> None:
    """ACA-4: a holiday stays a holiday."""
    day = dt.date(2026, 11, 14)
    term = make_term(
        non_study_days=[day], moved_days=[MovedDay(date=day, follows_weekday=1)]
    )

    assert effective_weekday(day, term) is None


@pytest.mark.parametrize(
    ("day", "weekday"),
    [(dt.date(2026, 10, 5), 1), (dt.date(2026, 10, 6), 2), (dt.date(2026, 10, 10), 6)],
)
def test_an_ordinary_day_keeps_its_weekday(day: dt.date, weekday: int) -> None:
    """ACA-5: ordinary study days use their own weekday."""
    assert effective_weekday(day, make_term()) == weekday


@pytest.mark.parametrize(
    ("day", "parity"),
    [
        (dt.date(2026, 9, 1), "odd"),  # the term starts on a Tuesday: week 1
        (dt.date(2026, 9, 6), "odd"),  # Sunday of week 1
        (dt.date(2026, 9, 7), "even"),  # Monday of week 2
        (dt.date(2026, 9, 14), "odd"),
        (dt.date(2026, 10, 6), "even"),  # 36 days after the first Monday: week 6
    ],
)
def test_week_parity_counts_weeks_from_the_monday_of_the_term_start(
    day: dt.date, parity: str
) -> None:
    """ACA-5: odd and even weeks alternate from the first week of the term."""
    assert week_parity(day, make_term()) == parity


def test_monday_of_returns_the_start_of_the_iso_week() -> None:
    """Helper: Monday of a Sunday is six days earlier."""
    assert monday_of(dt.date(2026, 9, 6)) == dt.date(2026, 8, 31)


def test_bell_for_uses_the_saturday_row() -> None:
    """ACA-4: Saturday can have different times."""
    term = make_term()

    assert bell_for(term, 1, 2) == (dt.time(8, 30), dt.time(9, 15))
    assert bell_for(term, 1, 6) == (dt.time(8, 30), dt.time(9, 5))


def test_bell_for_returns_none_for_an_unknown_period() -> None:
    """ACA-7: an entry without a bell cannot be scheduled."""
    assert bell_for(make_term(), 7, 2) is None


def test_lesson_times_convert_tashkent_to_utc() -> None:
    """Lessons are stored in UTC; bells are local Tashkent time (UTC+5)."""
    starts_at, ends_at = lesson_times(
        dt.date(2026, 10, 6), dt.time(8, 30), dt.time(9, 15)
    )

    assert starts_at == dt.datetime(2026, 10, 6, 3, 30, tzinfo=dt.UTC)
    assert ends_at == dt.datetime(2026, 10, 6, 4, 15, tzinfo=dt.UTC)
