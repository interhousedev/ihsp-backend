"""Pure attendance rules: who may edit, the edit window, the audience snapshot."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    AbsentOutsideRosterError,
    AttendanceCancelledLessonError,
    AttendanceWindowClosedError,
    NotLessonTeacherError,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.roster import Roster
from app.shared.actor import Actor, Role


def ensure_lesson_staff(lesson: Lesson, actor: Actor) -> None:
    """Allow Administration and the lesson's own teacher, refuse everyone else."""
    if actor.has(Role.ADMIN) or lesson.is_taught_by(actor.user_id):
        return
    raise NotLessonTeacherError(params={"lesson_id": str(lesson.id)})


def window_open(lesson: Lesson, today: dt.date, limit_days: int) -> bool:
    """True while the lesson is at most ``limit_days`` days in the past (ACA-11)."""
    return (today - lesson.date).days <= limit_days


def attendance_editable(
    lesson: Lesson, actor: Actor, today: dt.date, limit_days: int
) -> bool:
    """Administration always; the lesson's teacher within the window."""
    if actor.has(Role.ADMIN):
        return True
    return lesson.is_taught_by(actor.user_id) and window_open(lesson, today, limit_days)


def ensure_attendance_editable(
    lesson: Lesson, actor: Actor, today: dt.date, limit_days: int
) -> bool:
    """Check permission and window; return True when an admin edits after it.

    Raises:
        NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
        AttendanceWindowClosedError: a teacher edits after the window.
    """
    ensure_lesson_staff(lesson, actor)
    if lesson.status == "cancelled":
        raise AttendanceCancelledLessonError(params={"lesson_id": str(lesson.id)})
    in_window = window_open(lesson, today, limit_days)
    if in_window:
        return False
    if actor.has(Role.ADMIN):
        return True
    raise AttendanceWindowClosedError(
        params={"lesson_id": str(lesson.id), "days": limit_days}
    )


def build_snapshot(
    roster: Roster, absent: Sequence[UUID], present_unassigned: Sequence[UUID]
) -> list[UUID]:
    """Return the audience saved with the list.

    It is the expected students, the unassigned students the teacher marked
    present, and the unassigned students marked absent (ACA-2, ACA-11).

    Raises:
        AbsentOutsideRosterError: someone outside the roster was marked, or a
            student is both absent and present.
    """
    expected = roster.expected_ids()
    unassigned = roster.unassigned_ids()
    absent_set = set(absent)
    present_set = set(present_unassigned)
    outside = (absent_set - expected - unassigned) | (present_set - unassigned)
    clash = absent_set & present_set
    if outside or clash:
        bad = sorted(str(user_id) for user_id in outside | clash)
        raise AbsentOutsideRosterError(params={"user_ids": bad})
    included = expected | present_set | (absent_set & unassigned)
    return [s.user_id for s in roster.entries if s.user_id in included]
