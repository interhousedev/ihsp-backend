"""Who may attach what to a lesson (ACA-9, WEB-10)."""

from datetime import date, timedelta

STUDENT_DAYS_BEFORE = 7
STUDENT_DAYS_AFTER = 14
MAX_EXTRA_LESSONS = 20


def student_window_open(lesson_date: date, today: date) -> bool:
    """Students attach from 7 days after a lesson back to 14 days ahead."""
    earliest = today - timedelta(days=STUDENT_DAYS_BEFORE)
    latest = today + timedelta(days=STUDENT_DAYS_AFTER)
    return earliest <= lesson_date <= latest
