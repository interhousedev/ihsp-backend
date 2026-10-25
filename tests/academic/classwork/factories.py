"""Factories of pure domain objects for the classwork tests."""

import datetime as dt

from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.ids import new_id

TEACHER = new_id()
GROUP = new_id()
LESSON_DAY = dt.date(2026, 10, 6)


def make_lesson(**changes: object) -> Lesson:
    """A scheduled lesson on LESSON_DAY taught by TEACHER."""
    values: dict[str, object] = {
        "id": new_id(),
        "term_id": new_id(),
        "date": LESSON_DAY,
        "period": 1,
        "starts_at": dt.datetime(2026, 10, 6, 3, 30, tzinfo=dt.UTC),
        "ends_at": dt.datetime(2026, 10, 6, 4, 15, tzinfo=dt.UTC),
        "subject_id": new_id(),
        "subject_names": {"en": "Physics"},
        "subject_short": None,
        "teacher_id": TEACHER,
        "room_id": None,
        "room_slug": None,
        "room_name": None,
        "room_pin": None,
        "audience": (str(GROUP),),
        "groups": {GROUP: "2TN2"},
        "status": "scheduled",
        "topic": None,
        "is_overridden": False,
        "changes": None,
        "homework_text": None,
        "homework_due_date": None,
        "homework_due_auto": True,
        "homework_updated_at": None,
        "attendance_roster": None,
        "attendance_absent": None,
        "attendance_excused": None,
        "attendance_version": 0,
        "attendance_by": None,
        "attendance_at": None,
        "attendance_source": None,
    }
    values.update(changes)
    return Lesson(**values)  # type: ignore[arg-type]
