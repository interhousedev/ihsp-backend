"""ACA-12, STF-14, WEB-3: rates, flags and lesson states."""

import datetime as dt

from app.modules.academic.domain.classwork.reports import (
    day_states,
    minutes_until,
    rate,
    student_flags,
)
from tests.academic.classwork.factories import make_lesson

UTC = dt.UTC


def at(hour: int, minute: int = 0) -> dt.datetime:
    """A UTC moment on the lesson day."""
    return dt.datetime(2026, 10, 6, hour, minute, tzinfo=UTC)


def test_rate_is_absences_over_lessons_with_attendance() -> None:
    """ACA-12: no lessons means no rate, not zero."""
    assert rate(1, 4) == 0.25
    assert rate(0, 4) == 0.0
    assert rate(3, 0) is None


def test_curator_flags_high_absences_gpa_drop_and_missing_subgroup() -> None:
    """STF-14: the reasons a curator should look at a student."""
    assert student_flags(0.21, 4.0, 4.5, None) == [
        "absences",
        "gpa_drop",
        "no_subgroup",
    ]
    assert student_flags(0.2, 4.45, 4.5, 1) == []
    assert student_flags(None, None, None, 2) == []


def test_day_states_mark_done_now_next_later_and_cancelled() -> None:
    """WEB-3: the timeline of today."""
    done = make_lesson(period=1, starts_at=at(3), ends_at=at(4))
    now = make_lesson(period=2, starts_at=at(8), ends_at=at(9, 30))
    cancelled = make_lesson(
        period=3, starts_at=at(9, 40), ends_at=at(10, 20), status="cancelled"
    )
    nxt = make_lesson(period=4, starts_at=at(10, 30), ends_at=at(11, 15))
    later = make_lesson(period=5, starts_at=at(11, 25), ends_at=at(12, 10))

    states = day_states([later, nxt, cancelled, now, done], at(9))

    assert [(lesson.period, state) for lesson, state in states] == [
        (1, "done"),
        (2, "now"),
        (3, "cancelled"),
        (4, "next"),
        (5, "later"),
    ]


def test_minutes_until_rounds_up_and_is_never_negative() -> None:
    """UF-WEB-02: "in 12 min"."""
    assert minutes_until(at(9, 12), at(9)) == 12
    assert minutes_until(at(9, 0), at(9, 0)) == 0
    assert minutes_until(at(8, 0), at(9)) == 0
    assert minutes_until(dt.datetime(2026, 10, 6, 9, 0, 30, tzinfo=UTC), at(9)) == 1
