"""Pure calendar logic: which weekday a date follows, week parity, bell times."""

import datetime as dt
from typing import Literal

from app.modules.academic.domain.schedule.school_days import SCHOOL_DAYS
from app.modules.academic.domain.schedule.term import Term
from app.shared.clock import TASHKENT

Parity = Literal["odd", "even"]


def monday_of(day: dt.date) -> dt.date:
    """Return the Monday of the ISO week containing the day."""
    return day - dt.timedelta(days=day.isoweekday() - 1)


def effective_weekday(day: dt.date, term: Term) -> int | None:
    """Return the weekday (1-5) whose timetable applies on the day, or None.

    None means no lessons: a non-study day, or a Saturday or Sunday. Only Monday to
    Friday can be a study day; a moved-day rule on a weekend (kept from before) is
    ignored, and a moved day follows another Monday-to-Friday weekday.
    """
    if day in term.non_study_days:
        return None
    weekday = day.isoweekday()
    if weekday not in SCHOOL_DAYS:
        return None
    for moved in term.moved_days:
        if moved.date == day:
            follows = moved.follows_weekday
            return follows if follows in SCHOOL_DAYS else None
    return weekday


def term_week(day: dt.date, term: Term) -> int:
    """Return the number of the term's week that holds the day (the first is 1).

    The anchor is the term's first Monday: the Monday of the week that contains
    ``term.starts_on``. Weeks before the term have numbers below 1.
    """
    return ((day - monday_of(term.starts_on)).days // 7) + 1


def parity_of_week(week: int) -> Parity:
    """Return "odd" for weeks 1, 3, 5 ... and "even" for weeks 2, 4, 6 ..."""
    return "odd" if week % 2 == 1 else "even"


def week_parity(day: dt.date, term: Term) -> Parity:
    """Return "odd" or "even": the week counts from the term's first Monday."""
    return parity_of_week(term_week(day, term))


def bell_for(term: Term, period: int, weekday: int) -> tuple[dt.time, dt.time] | None:
    """Return (start, end) of the period on the weekday, or None without a bell."""
    for bell in term.bells:
        if bell.period == period and weekday in bell.weekdays:
            return bell.start, bell.end
    return None


def lesson_times(
    day: dt.date, start: dt.time, end: dt.time
) -> tuple[dt.datetime, dt.datetime]:
    """Return the lesson's start and end as UTC datetimes (bells are Tashkent time)."""
    begin = dt.datetime.combine(day, start, tzinfo=TASHKENT)
    finish = dt.datetime.combine(day, end, tzinfo=TASHKENT)
    return begin.astimezone(dt.UTC), finish.astimezone(dt.UTC)
