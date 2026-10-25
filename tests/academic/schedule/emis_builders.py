"""EmisClass builders for the tests of the EMIS timetable sync (week 0 starts 5 Oct)."""

import datetime as dt
from typing import Any, Literal

from app.shared.contracts.emis import (
    EmisClass,
    EmisSubject,
    EmisTeacher,
    EmisTopic,
)
from app.shared.lesson_kind import LessonKind

WEEK0 = dt.date(
    2026, 10, 5
)  # the Monday of the FixedClock week; term week 6 of 2026-09-01
WEEKS = (0, 1, 2, 3)

MATH = EmisSubject(101, "Matematika", "Математика", "Mathematics")
PHYSICS = EmisSubject(102, "Fizika", "Физика", "Physics")
HISTORY = EmisSubject(106, "Tarix", "История", "History")
KALANDAROVA = EmisTeacher(9001, "Gulnora", "Kalandarova", "Akbarovna")
YULDASHEV = EmisTeacher(9002, "Sardor", "Yuldashev", None)


def day(week: int, weekday: int) -> dt.date:
    """The date of a weekday (1 = Monday) in the nth week of the window."""
    return WEEK0 + dt.timedelta(days=7 * week + weekday - 1)


def klass(
    week: int,
    weekday: int,
    pair: int = 0,
    *,
    subject: EmisSubject = MATH,
    teacher: EmisTeacher | None = KALANDAROVA,
    room: str | None = "101",
    subgroup: Literal[1, 2] | None = None,
    kind: LessonKind = "lecture",
    topic: EmisTopic | None = None,
    class_id: int | None = None,
) -> EmisClass:
    """One class; its id follows from where and for whom it is, unless given."""
    when = day(week, weekday)
    default_id = 3_000_000 + when.toordinal() * 100 + pair * 10 + (subgroup or 0)
    return EmisClass(
        class_id=class_id or default_id,
        date=when,
        pair_number=pair,
        subject=subject,
        teacher=teacher,
        room=room,
        subgroup=subgroup,
        kind=kind,
        topic=topic,
    )


def weekly(
    weekday: int, pair: int = 0, weeks: tuple[int, ...] = WEEKS, **kwargs: Any
) -> list[EmisClass]:
    """The same class in each of the weeks."""
    return [klass(week, weekday, pair, **kwargs) for week in weeks]
