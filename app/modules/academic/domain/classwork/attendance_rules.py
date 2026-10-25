"""Pure attendance rules: who may edit, the audience snapshot."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    AbsentOutsideRosterError,
    AttendanceCancelledLessonError,
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


def attendance_editable(lesson: Lesson, actor: Actor) -> bool:
    """Administration and the lesson's teacher, for any lesson, at any time."""
    return actor.has(Role.ADMIN) or lesson.is_taught_by(actor.user_id)


def ensure_attendance_editable(lesson: Lesson, actor: Actor) -> None:
    """Check permission and that the lesson is not cancelled.

    Raises:
        NotLessonTeacherError: the actor neither teaches the lesson nor is admin.
        AttendanceCancelledLessonError: the lesson is cancelled.
    """
    ensure_lesson_staff(lesson, actor)
    if lesson.status == "cancelled":
        raise AttendanceCancelledLessonError(params={"lesson_id": str(lesson.id)})


def build_snapshot(
    roster: Roster,
    absent: Sequence[UUID],
    present_unassigned: Sequence[UUID],
    late: Sequence[UUID] = (),
) -> list[UUID]:
    """Return the audience saved with the list.

    It is the expected students, the unassigned students the teacher marked
    present or late, and the unassigned students marked absent (ACA-2, ACA-11).

    Raises:
        AbsentOutsideRosterError: someone outside the roster was marked, or a
            student is both absent and present.
    """
    expected = roster.expected_ids()
    unassigned = roster.unassigned_ids()
    absent_set = set(absent)
    late_set = set(late)
    present_set = set(present_unassigned)
    outside = (
        (absent_set - expected - unassigned)
        | (late_set - expected - unassigned)
        | (present_set - unassigned)
    )
    clash = (
        (absent_set & present_set) | (absent_set & late_set) | (late_set & present_set)
    )
    if outside or clash:
        bad = sorted(str(user_id) for user_id in outside | clash)
        raise AbsentOutsideRosterError(params={"user_ids": bad})
    included = expected | present_set | ((absent_set | late_set) & unassigned)
    return [s.user_id for s in roster.entries if s.user_id in included]
