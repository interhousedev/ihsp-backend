"""An approved excuse locks the student's attendance as absent and excused."""

from app.modules.academic.domain.classwork.excuse_ref import ExcuseRef
from app.modules.academic.domain.excuses.errors import AttendanceExcusedLockedError
from app.shared.ids import new_id
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import add_lesson, lesson_row

import pytest


async def test_a_covered_student_is_saved_absent_and_excused(env: Env) -> None:
    """The submit adds the student to the absent list and links the excuse."""
    w = env.world
    excuse_id = new_id()
    env.coverage.covered[w.aziz.id] = ExcuseRef(excuse_id, "illness", "request")
    lesson_id = await add_lesson(env.maker, w)

    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[],
        base_version=0,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert w.aziz.id in (row.attendance_absent or [])
    mark = (row.attendance_excused or {})[str(w.aziz.id)]
    assert mark["comment"] == f"excuse:{excuse_id}:illness:request"


async def test_a_covered_student_cannot_be_marked_late(env: Env) -> None:
    """Late is a presence: it contradicts the excuse."""
    w = env.world
    env.coverage.covered[w.aziz.id] = ExcuseRef(new_id(), "illness", "curator")
    lesson_id = await add_lesson(env.maker, w)

    with pytest.raises(AttendanceExcusedLockedError):
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.teacher,
            absent=[],
            late=[w.aziz.id],
            base_version=0,
            source="staff",
        )


async def test_the_journal_cell_of_a_covered_student_is_locked(env: Env) -> None:
    """Un-marking the absence in the grid is refused."""
    w = env.world
    env.coverage.covered[w.aziz.id] = ExcuseRef(new_id(), "illness", "curator")
    lesson_id = await add_lesson(env.maker, w)

    with pytest.raises(AttendanceExcusedLockedError):
        await env.services.toggle_journal_cell.execute(
            lesson_id=lesson_id,
            student_id=w.aziz.id,
            absent=False,
            base_version=0,
            actor=env.teacher,
        )


async def test_the_curator_cannot_remove_the_excuse_of_a_covered_student(
    env: Env,
) -> None:
    """SetExcuse(excused=False) is refused while the excuse covers the lesson."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
    )
    env.coverage.covered[w.aziz.id] = ExcuseRef(new_id(), "illness", "curator")

    with pytest.raises(AttendanceExcusedLockedError):
        await env.services.set_excuse.execute(
            lesson_id=lesson_id,
            student_id=w.aziz.id,
            excused=False,
            comment=None,
            actor=env.curator,
        )
