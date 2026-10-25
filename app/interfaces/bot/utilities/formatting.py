"""Plain-text formatting of dates, times and lessons in Tashkent time."""

from datetime import date, datetime

from app.shared.clock import to_local
from app.shared.contracts.academic import LessonRef

# i18n key of every mark type (also used as a literal-key catalogue for tests).
MARK_TYPE_KEYS = {
    "lesson": "bot-mark-type-lesson",
    "midterm": "bot-mark-type-midterm",
    "final": "bot-mark-type-final",
}


def fmt_time(value: datetime) -> str:
    """Return ``HH:MM`` in Tashkent time."""
    return to_local(value).strftime("%H:%M")


def fmt_date(value: date | datetime) -> str:
    """Return ``DD.MM`` (a datetime is converted to Tashkent first)."""
    if isinstance(value, datetime):
        value = to_local(value).date()
    return value.strftime("%d.%m")


def fmt_datetime(value: datetime) -> str:
    """Return ``DD.MM HH:MM`` in Tashkent time."""
    return to_local(value).strftime("%d.%m %H:%M")


def time_range(lesson: LessonRef) -> str:
    """Return ``HH:MM–HH:MM`` for the lesson."""
    return f"{fmt_time(lesson.starts_at)}–{fmt_time(lesson.ends_at)}"


def groups_label(lesson: LessonRef) -> str:
    """Return the audience groups, e.g. ``2TN2, 2TN3``."""
    return ", ".join(lesson.group_names)


def lesson_label(lesson: LessonRef) -> str:
    """Return a short one-line name: date, time, subject and groups."""
    parts = [fmt_date(lesson.date), fmt_time(lesson.starts_at), lesson.subject_name]
    groups = groups_label(lesson)
    return " ".join(parts) + (f" · {groups}" if groups else "")


def number(value: float | None) -> str:
    """Return a mark or GPA with two decimals, or a dash."""
    return "—" if value is None else f"{value:.2f}"
