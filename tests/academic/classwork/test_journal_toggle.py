"""STF-9, UF-STF-07: toggling one absence in the journal grid."""

import datetime as dt

from app.modules.academic.domain.classwork.errors import (
    AbsentOutsideRosterError,
    AttendanceConflictError,
    AttendanceWindowClosedError,
)
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, lesson_row

import pytest


async def test_toggle_marks_the_student_absent_and_saves_the_audience(env: Env) -> None:
    """STF-9: the first toggle of an untouched lesson saves the whole audience."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    version = await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=True,
        base_version=0,
        actor=env.teacher,
    )

    row = await lesson_row(env.maker, lesson_id)
    assert version == 1
    assert row.attendance_absent == [w.aziz.id]
    assert set(row.attendance_roster or []) == {w.aziz.id, w.bobur.id, w.camila.id}
    assert row.attendance_source == "staff"


async def test_two_toggles_with_the_same_base_version_the_second_gets_409(
    env: Env,
) -> None:
    """ACA-11: single statement with a version check; two editors never collide."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=True,
        base_version=0,
        actor=env.teacher,
    )

    with pytest.raises(AttendanceConflictError) as error:
        await env.services.toggle_journal_cell.execute(
            lesson_id=lesson_id,
            student_id=w.bobur.id,
            absent=True,
            base_version=0,
            actor=env.teacher,
        )

    assert error.value.params["version"] == 1
    assert (await lesson_row(env.maker, lesson_id)).attendance_absent == [w.aziz.id]


async def test_toggle_off_with_the_new_version_clears_the_cell_and_the_excuse(
    env: Env,
) -> None:
    """ACA-20: un-marking an absence removes its excuse in the same statement."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=True,
        base_version=0,
        actor=env.teacher,
    )
    await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        excused=True,
        comment=None,
        actor=env.curator,
    )

    version = await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=False,
        base_version=2,
        actor=env.teacher,
    )

    row = await lesson_row(env.maker, lesson_id)
    assert version == 3
    assert row.attendance_absent == []
    assert row.attendance_excused is None


async def test_toggle_keeps_other_absences_of_the_lesson(env: Env) -> None:
    """The statement changes one student, not the list."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    for base, student in enumerate((w.aziz, w.bobur)):
        await env.services.toggle_journal_cell.execute(
            lesson_id=lesson_id,
            student_id=student.id,
            absent=True,
            base_version=base,
            actor=env.teacher,
        )

    row = await lesson_row(env.maker, lesson_id)
    assert set(row.attendance_absent or []) == {w.aziz.id, w.bobur.id}


async def test_unassigned_student_absent_is_added_to_the_roster(env: Env) -> None:
    """ACA-2: an unassigned absence is counted."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])

    await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.camila.id,
        absent=True,
        base_version=0,
        actor=env.teacher,
    )

    row = await lesson_row(env.maker, lesson_id)
    assert set(row.attendance_roster or []) == {w.aziz.id, w.camila.id}
    assert row.attendance_absent == [w.camila.id]


async def test_student_outside_the_audience_is_refused(env: Env) -> None:
    """ACA-11: only students of the audience can be marked."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    with pytest.raises(AbsentOutsideRosterError):
        await env.services.toggle_journal_cell.execute(
            lesson_id=lesson_id,
            student_id=w.outsider.id,
            absent=True,
            base_version=0,
            actor=env.teacher,
        )


async def test_older_than_seven_days_is_read_only_for_teachers(env: Env) -> None:
    """UF-STF-07 3a: lessons older than seven days are read-only."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=8))

    with pytest.raises(AttendanceWindowClosedError):
        await env.services.toggle_journal_cell.execute(
            lesson_id=lesson_id,
            student_id=w.aziz.id,
            absent=True,
            base_version=0,
            actor=env.teacher,
        )


async def test_administration_toggle_after_the_window_is_audited(env: Env) -> None:
    """ACA-11: Administration corrects old attendance and it is logged."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=8))

    await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=True,
        base_version=0,
        actor=env.admin,
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_source == "admin"
    assert [a.type for a in env.outbox.audits] == ["attendance.late_edit"]


async def test_toggle_late_marks_the_student_late_not_absent(env: Env) -> None:
    """A late cell is saved in the late list and clears the absence."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=True,
        base_version=0,
        actor=env.teacher,
    )

    await env.services.toggle_journal_cell.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        absent=False,
        late=True,
        base_version=1,
        actor=env.teacher,
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_absent == []
    assert row.attendance_late == [w.aziz.id]
