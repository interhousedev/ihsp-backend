"""ACA-11, ACA-2: permissions, cancelled lessons and the audience snapshot."""

from uuid import UUID

from app.modules.academic.domain import audience
from app.modules.academic.domain.classwork.attendance_rules import (
    attendance_editable,
    build_snapshot,
    ensure_attendance_editable,
)
from app.modules.academic.domain.classwork.errors import (
    AbsentOutsideRosterError,
    AttendanceCancelledLessonError,
    NotLessonTeacherError,
)
from app.modules.academic.domain.classwork.roster import RosterStudent, build_roster
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.academic.classwork.factories import GROUP, TEACHER, make_lesson

import pytest


def actor(role: Role, user_id: UUID | None = None) -> Actor:
    """An actor with one role."""
    return Actor(user_id=user_id or new_id(), roles=frozenset({role}))


def test_teacher_may_edit_a_lesson_of_any_age() -> None:
    """ACA-11: no time window; the lesson's teacher edits at any date."""
    lesson = make_lesson()
    teacher = actor(Role.TEACHER, TEACHER)

    assert attendance_editable(lesson, teacher)
    ensure_attendance_editable(lesson, teacher)


def test_administration_may_edit_any_lesson() -> None:
    """ACA-11: Administration edits any lesson."""
    lesson = make_lesson()
    admin = actor(Role.ADMIN)

    assert attendance_editable(lesson, admin)
    ensure_attendance_editable(lesson, admin)


def test_another_teacher_is_refused() -> None:
    """STF-8: only the lesson's teacher or Administration."""
    with pytest.raises(NotLessonTeacherError):
        ensure_attendance_editable(make_lesson(), actor(Role.TEACHER))
    assert not attendance_editable(make_lesson(), actor(Role.TEACHER))


def test_a_cancelled_lesson_takes_no_attendance() -> None:
    """Attendance for cancelled lessons is refused."""
    with pytest.raises(AttendanceCancelledLessonError):
        ensure_attendance_editable(
            make_lesson(status="cancelled"), actor(Role.TEACHER, TEACHER)
        )


def _roster() -> tuple[RosterStudent, RosterStudent, RosterStudent]:
    def student(last: str, subgroup: int | None) -> RosterStudent:
        return RosterStudent(new_id(), "X", last, GROUP, "2TN2", subgroup)

    return student("A", 1), student("B", 2), student("C", None)


def test_snapshot_is_the_expected_students_of_the_subgroup() -> None:
    """ACA-2: unassigned students are not counted unless marked."""
    a, b, c = _roster()
    roster = build_roster([audience.key(GROUP, 1)], [a, b, c])

    snapshot = build_snapshot(roster, absent=[], present_unassigned=[])

    assert snapshot == [a.user_id]


def test_unassigned_student_marked_present_joins_the_snapshot() -> None:
    """ACA-2: counted only if the teacher marks them."""
    a, b, c = _roster()
    roster = build_roster([audience.key(GROUP, 1)], [a, b, c])

    snapshot = build_snapshot(roster, absent=[], present_unassigned=[c.user_id])

    assert snapshot == [a.user_id, c.user_id]


def test_unassigned_student_marked_absent_joins_the_snapshot() -> None:
    """ACA-2: an unassigned absence is counted."""
    a, b, c = _roster()
    roster = build_roster([audience.key(GROUP, 1)], [a, b, c])

    snapshot = build_snapshot(roster, absent=[c.user_id], present_unassigned=[])

    assert c.user_id in snapshot


def test_absent_student_outside_the_roster_is_refused() -> None:
    """ACA-11: only students of the audience can be marked."""
    a, b, c = _roster()
    roster = build_roster([audience.key(GROUP, 1)], [a, b, c])

    with pytest.raises(AbsentOutsideRosterError):
        build_snapshot(roster, absent=[b.user_id], present_unassigned=[])


def test_present_list_may_only_name_unassigned_students() -> None:
    """present_unassigned lists students without a subgroup only."""
    a, b, c = _roster()
    roster = build_roster([audience.key(GROUP, 1)], [a, b, c])

    with pytest.raises(AbsentOutsideRosterError):
        build_snapshot(roster, absent=[], present_unassigned=[a.user_id])


def test_a_student_cannot_be_absent_and_present() -> None:
    """The two lists must not overlap."""
    a, b, c = _roster()
    roster = build_roster([audience.key(GROUP, 1)], [a, b, c])

    with pytest.raises(AbsentOutsideRosterError):
        build_snapshot(roster, absent=[c.user_id], present_unassigned=[c.user_id])
