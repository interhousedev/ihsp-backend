"""ACA-20, UF-STF-11: the curator marks absences as excused."""

from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    ExcuseNotAbsentError,
    NotCuratorError,
)
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import add_lesson, lesson_row

import pytest


async def _absent_lesson(env: Env) -> UUID:
    lesson_id = await add_lesson(env.maker, env.world)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[env.world.aziz.id, env.world.bobur.id],
        base_version=0,
        source="staff",
    )
    return lesson_id


async def test_curator_excuses_an_absence_with_a_comment(env: Env) -> None:
    """ACA-20: excused and unexcused absences are kept apart."""
    w = env.world
    lesson_id = await _absent_lesson(env)

    sheet = await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        excused=True,
        comment="  Medical note  ",
        actor=env.curator,
    )

    aziz = sheet["roster"][0]
    assert aziz["excused"] is True
    assert aziz["excuse_comment"] == "Medical note"
    assert sheet["roster"][1]["excused"] is False
    row = await lesson_row(env.maker, lesson_id)
    mark = (row.attendance_excused or {})[str(w.aziz.id)]
    assert mark["by"] == str(w.curator.id)
    assert row.attendance_absent == [w.aziz.id, w.bobur.id]


async def test_curator_sheet_is_read_only(env: Env) -> None:
    """The curator can excuse but not edit the teacher's list."""
    lesson_id = await _absent_lesson(env)

    sheet = await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=env.world.aziz.id,
        excused=True,
        comment=None,
        actor=env.curator,
    )

    assert sheet["editable"] is False


async def test_excuse_can_be_withdrawn(env: Env) -> None:
    """ACA-20: the curator can undo an excuse."""
    w = env.world
    lesson_id = await _absent_lesson(env)
    await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        excused=True,
        comment=None,
        actor=env.curator,
    )

    sheet = await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        excused=False,
        comment=None,
        actor=env.curator,
    )

    assert sheet["roster"][0]["excused"] is False
    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_excused is None


async def test_only_an_absent_student_can_be_excused(env: Env) -> None:
    """ACA-20: keys of the excuse map are always a subset of the absent list."""
    lesson_id = await _absent_lesson(env)

    with pytest.raises(ExcuseNotAbsentError):
        await env.services.set_excuse.execute(
            lesson_id=lesson_id,
            student_id=env.world.camila.id,
            excused=True,
            comment=None,
            actor=env.curator,
        )


async def test_a_teacher_who_does_not_curate_the_group_is_refused(env: Env) -> None:
    """ACA-20: the curator of the student's group, or Administration."""
    lesson_id = await _absent_lesson(env)

    with pytest.raises(NotCuratorError):
        await env.services.set_excuse.execute(
            lesson_id=lesson_id,
            student_id=env.world.aziz.id,
            excused=True,
            comment=None,
            actor=env.other_teacher,
        )


async def test_administration_can_excuse_any_absence(env: Env) -> None:
    """ACA-20: Administration may excuse too."""
    lesson_id = await _absent_lesson(env)

    sheet = await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=env.world.bobur.id,
        excused=True,
        comment=None,
        actor=env.admin,
    )

    assert sheet["roster"][1]["excused"] is True
