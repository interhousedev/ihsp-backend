"""Validating the from/to range of timetable requests."""

import datetime as dt

from app.shared.base_error import ValidationFailedError

DEFAULT_DAYS = 7
MAX_DAYS = 93


class InvalidDateRangeError(ValidationFailedError):
    """The range is reversed or longer than three months."""

    code = "academic/invalid-date-range"
    message_key = "academic-invalid-date-range"


def resolve_range(
    start: dt.date | None, end: dt.date | None, today: dt.date
) -> tuple[dt.date, dt.date]:
    """Fill defaults (today, one week) and check the range."""
    first = start or today
    last = end or first + dt.timedelta(days=DEFAULT_DAYS - 1)
    if last < first or (last - first).days >= MAX_DAYS:
        raise InvalidDateRangeError(
            params={"from": first.isoformat(), "to": last.isoformat()}
        )
    return first, last
