"""SQL conditions that keep retired rows and non-school days out of reads.

Saturday lessons from before Saturday could be opened stay in the tables untouched;
every read skips them. A later Saturday lesson is real, because the term has blocks on
that day. The next-school-day lookups use ``on_school_day``, which also skips the
older Sunday lessons.
"""

from typing import Any

from app.modules.academic.domain.schedule.school_days import (
    SATURDAY,
    SCHOOL_DAYS,
    WEEK_DAYS,
    WEEKEND_LESSONS_SINCE,
)

import sqlalchemy as sa
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement

NOT_SATURDAY_SQL = (
    f"(extract(isodow FROM l.date) <> {SATURDAY} "
    f"OR l.date >= DATE '{WEEKEND_LESSONS_SINCE.isoformat()}')"
)
"""Raw SQL for queries that alias the lessons table as ``l``."""


def not_on_saturday(date_column: ColumnElement[Any] | QueryableAttribute[Any]) -> Any:
    """False only for Saturdays from before Saturday could hold lessons."""
    return sa.or_(
        sa.extract("isodow", date_column) != SATURDAY,
        date_column >= WEEKEND_LESSONS_SINCE,
    )


def on_school_day(date_column: ColumnElement[Any] | QueryableAttribute[Any]) -> Any:
    """True for Monday to Friday, and a weekend since weekends could be opened."""
    return sa.or_(
        sa.extract("isodow", date_column).in_(SCHOOL_DAYS),
        date_column >= WEEKEND_LESSONS_SINCE,
    )


def entry_on_school_day(weekday: QueryableAttribute[Any]) -> ColumnElement[bool]:
    """True for timetable entries that are not retired (weekdays 1 to 7)."""
    return weekday.in_(WEEK_DAYS)
