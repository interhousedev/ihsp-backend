"""Semester numbers and the dates a semester covers."""

import datetime as dt
from collections.abc import Collection, Sequence

MIN_SEMESTER = 1
MAX_SEMESTER = 4


def resolve_semester(
    requested: int | None, current: int | None, available: Collection[int]
) -> int:
    """Pick the semester to show: requested, else current, else latest with data."""
    if requested is not None:
        return requested
    if current is not None:
        return current
    return max(available, default=MIN_SEMESTER)


def semester_window(
    terms: Sequence[tuple[dt.date, dt.date]],
    current_semester: int | None,
    semester: int,
    today: dt.date,
) -> tuple[dt.date, dt.date] | None:
    """Return the dates of a semester, assuming one term per semester.

    The term that holds today (or the last one that started) is the current
    semester; earlier semesters map to the terms before it. Returns None when
    the calendar has no such term.
    """
    if current_semester is None:
        return None
    ordered = sorted(terms)
    started = [i for i, (start, _end) in enumerate(ordered) if start <= today]
    if not started:
        return None
    index = started[-1] - (current_semester - semester)
    if 0 <= index < len(ordered):
        return ordered[index]
    return None
