"""Pure numbers behind attendance reports and the Today cards."""

import datetime as dt
from collections.abc import Sequence
from typing import Literal

from app.modules.academic.domain.classwork.lesson import Lesson

ABSENCE_FLAG_RATE = 0.2
GPA_DROP_FLAG = 0.1

LessonState = Literal["done", "now", "next", "later", "cancelled"]
Flag = Literal["absences", "gpa_drop", "no_subgroup"]


def rate(absences: int, lessons: int) -> float | None:
    """Absence rate = absences / lessons with taken attendance (ACA-12)."""
    if lessons <= 0:
        return None
    return round(absences / lessons, 4)


def student_flags(
    absence_rate: float | None,
    gpa: float | None,
    previous_gpa: float | None,
    subgroup: int | None,
) -> list[Flag]:
    """Reasons a curator should look at a student (STF-14)."""
    flags: list[Flag] = []
    if absence_rate is not None and absence_rate > ABSENCE_FLAG_RATE:
        flags.append("absences")
    if gpa is not None and previous_gpa is not None:
        if gpa < previous_gpa - GPA_DROP_FLAG:
            flags.append("gpa_drop")
    if subgroup is None:
        flags.append("no_subgroup")
    return flags


def day_states(
    lessons: Sequence[Lesson], now: dt.datetime
) -> list[tuple[Lesson, LessonState]]:
    """Mark a day's lessons done, now, next, later or cancelled (WEB-3)."""
    ordered = sorted(lessons, key=lambda lesson: (lesson.starts_at, lesson.period))
    next_taken = False
    result: list[tuple[Lesson, LessonState]] = []
    for lesson in ordered:
        state: LessonState
        if lesson.status == "cancelled":
            state = "cancelled"
        elif lesson.ends_at <= now:
            state = "done"
        elif lesson.starts_at <= now:
            state = "now"
        elif not next_taken:
            state, next_taken = "next", True
        else:
            state = "later"
        result.append((lesson, state))
    return result


def minutes_until(target: dt.datetime, now: dt.datetime) -> int:
    """Whole minutes from now to the target, rounded up, never negative."""
    seconds = (target - now).total_seconds()
    return max(0, int((seconds + 59) // 60))
