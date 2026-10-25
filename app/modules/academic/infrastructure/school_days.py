"""SQL conditions that keep non-school days out of reads.

The lyceum has no Saturday lessons. Lessons and timetable entries written before
that stay in the tables untouched; every read skips the Saturday ones. A Sunday
lesson (a moved study day from before) is real and stays visible in lesson reads.
The next-school-day lookups use ``on_school_day``, which is Monday to Friday only.
"""

from typing import Any

from app.modules.academic.domain.schedule.school_days import (
    SATURDAY,
    SCHOOL_DAYS,
)

import sqlalchemy as sa
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement

NOT_SATURDAY_SQL = f"extract(isodow FROM l.date) <> {SATURDAY}"
"""Raw SQL for queries that alias the lessons table as ``l``."""


def not_on_saturday(date_column: ColumnElement[Any] | QueryableAttribute[Any]) -> Any:
    """True for dates that are not a Saturday (``isodow`` is the ISO weekday)."""
    return sa.extract("isodow", date_column) != SATURDAY


def on_school_day(date_column: ColumnElement[Any] | QueryableAttribute[Any]) -> Any:
    """True for dates Monday to Friday (``isodow`` is the ISO weekday)."""
    return sa.extract("isodow", date_column).in_(SCHOOL_DAYS)


def entry_on_school_day(weekday: QueryableAttribute[Any]) -> ColumnElement[bool]:
    """True for timetable entries whose weekday is Monday to Friday."""
    return weekday.in_(SCHOOL_DAYS)
