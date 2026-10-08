"""Pure calendar logic: which weekday a date follows, week parity, bell times."""

import datetime as dt
from typing import Literal

from app.modules.academic.domain.schedule.term import Term
from app.shared.clock import TASHKENT

Parity = Literal["odd", "even"]
SUNDAY = 7


def monday_of(day: dt.date) -> dt.date:
    """Return the Monday of the ISO week containing the day."""
    return day - dt.timedelta(days=day.isoweekday() - 1)


def effective_weekday(day: dt.date, term: Term) -> int | None:
    """Return the weekday (1-6) whose timetable applies on the day, or None.

    None means no lessons: a non-study day, or a Sunday without a moved-day rule.
    """
    if day in term.non_study_days:
        return None
    for moved in term.moved_days:
        if moved.date == day:
            return moved.follows_weekday
    weekday = day.isoweekday()
    return None if weekday == SUNDAY else weekday


def week_parity(day: dt.date, term: Term) -> Parity:
    """Return "odd" or "even": the week index counts from the term's first Monday."""
    index = ((day - monday_of(term.starts_on)).days // 7) + 1
    return "odd" if index % 2 == 1 else "even"


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
