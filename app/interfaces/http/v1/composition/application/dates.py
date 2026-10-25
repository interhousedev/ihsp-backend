"""Date windows used by the composed pages."""

import datetime as dt

# Teachers can still fill in attendance for 7 days (ACA-9), so older gaps are history.
MISSING_ATTENDANCE_DAYS = 7


def week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    """Return Monday and Sunday of the week that contains `day`."""
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=6)


def missing_attendance_window(today: dt.date) -> tuple[dt.date, dt.date]:
    """Return the dates between which lessons without attendance are reported."""
    return today - dt.timedelta(days=MISSING_ATTENDANCE_DAYS), today
