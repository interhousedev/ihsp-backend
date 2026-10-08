"""ACA-2, ACA-11, ACA-21, STF-8, UF-STF-06: taking and editing attendance."""

import datetime as dt

from app.modules.academic.domain.classwork.errors import (
    AbsentOutsideRosterError,
    AttendanceConflictError,
    AttendanceWindowClosedError,
    NotLessonTeacherError,
)
from app.modules.academic.infrastructure.orm.student import Student
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, lesson_row

import pytest
import sqlalchemy as sa


async def test_absent_list_is_saved_with_audience_snapshot(env: Env) -> None:
    """ACA-11, UF-STF-06: exactly who was absent, plus the audience at that moment."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    sheet = await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.bobur.id],
        base_version=0,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_absent == [w.bobur.id]
    assert set(row.attendance_roster or []) == {w.aziz.id, w.bobur.id, w.camila.id}
    assert row.attendance_version == 1
    assert row.attendance_source == "staff"
    assert row.attendance_by == w.teacher.id
    assert sheet["submitted"] is True
    assert sheet["version"] == 1
    assert [item["last_name"] for item in sheet["roster"]] == [
        "Abdullaev",
        "Karimov",
        "Rakhimova",
    ]
    assert [item["absent"] for item in sheet["roster"]] == [False, True, False]


async def test_everyone_present_is_different_from_not_submitted(env: Env) -> None:
    """ACA-11: an empty absent list is a submitted sheet."""
    lesson_id = await add_lesson(env.maker, env.world)
    before = await lesson_row(env.maker, lesson_id)

    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[],
        base_version=0,
        source="bot",
    )

    after = await lesson_row(env.maker, lesson_id)
    assert before.attendance_absent is None
    assert after.attendance_absent == []
    assert after.attendance_source == "bot"


async def test_absent_student_outside_the_audience_is_refused(env: Env) -> None:
    """ACA-11: subgroup 2 is not in a lesson for subgroup 1."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])

    with pytest.raises(AbsentOutsideRosterError):
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.teacher,
            absent=[w.bobur.id],
            base_version=0,
            source="staff",
        )

    assert (await lesson_row(env.maker, lesson_id)).attendance_absent is None


async def test_unassigned_student_is_counted_only_if_the_teacher_marks_them(
    env: Env,
) -> None:
    """ACA-2: students without a subgroup are separate in a subgroup lesson."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])

    sheet = await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[],
        base_version=0,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_roster == [w.aziz.id]
    camila = next(i for i in sheet["roster"] if i["user_id"] == str(w.camila.id))
    assert camila["subgroup_unset"] is True
    assert camila["counted"] is False


async def test_unassigned_student_marked_present_appears_in_the_roster(
    env: Env,
) -> None:
    """ACA-2: present_unassigned puts the student into the saved audience."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])

    sheet = await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[],
        present_unassigned=[w.camila.id],
        base_version=0,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert set(row.attendance_roster or []) == {w.aziz.id, w.camila.id}
    camila = next(i for i in sheet["roster"] if i["user_id"] == str(w.camila.id))
    assert camila["counted"] is True
    assert camila["absent"] is False


async def test_unassigned_student_marked_absent_is_in_roster_and_absent(
    env: Env,
) -> None:
    """ACA-2: an unassigned absence is counted too."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])

    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.camila.id],
        base_version=0,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_absent == [w.camila.id]
    assert w.camila.id in (row.attendance_roster or [])


async def test_stale_base_version_is_a_conflict_with_the_current_sheet(
    env: Env,
) -> None:
    """ACA-11: edits never silently overwrite each other."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="bot",
    )

    with pytest.raises(AttendanceConflictError) as error:
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.teacher,
            absent=[w.bobur.id],
            base_version=0,
            source="staff",
        )

    assert error.value.code == "common/conflict"
    current = error.value.params["current"]
    assert current["version"] == 1
    assert [i["absent"] for i in current["roster"]] == [True, False, False]
    assert (await lesson_row(env.maker, lesson_id)).attendance_absent == [w.aziz.id]


async def test_resubmitting_with_the_new_version_replaces_the_list(env: Env) -> None:
    """ACA-11: the teacher can edit within the window."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="bot",
    )

    sheet = await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.bobur.id],
        base_version=1,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_absent == [w.bobur.id]
    assert sheet["version"] == 2


async def test_teacher_after_the_window_is_refused_on_day_eight(env: Env) -> None:
    """ACA-11: seven days are allowed, the eighth is not."""
    w = env.world
    ok = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=7), period=1)
    late = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=8), period=1)

    await env.services.submit_attendance.execute(
        lesson_id=ok, actor=env.teacher, absent=[], base_version=0, source="staff"
    )
    with pytest.raises(AttendanceWindowClosedError) as error:
        await env.services.submit_attendance.execute(
            lesson_id=late, actor=env.teacher, absent=[], base_version=0, source="staff"
        )

    assert error.value.code == "attendance/window-closed"


async def test_administration_edits_after_the_window_and_it_is_audited(
    env: Env,
) -> None:
    """ACA-11: only Administration can edit after seven days."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=30))

    sheet = await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.admin,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_source == "admin"
    assert row.attendance_by == w.admin.id
    assert sheet["editable"] is True
    assert [a.type for a in env.outbox.audits] == ["attendance.late_edit"]
    assert env.outbox.audits[0].actor_id == w.admin.id


async def test_in_window_edit_by_administration_is_not_a_late_edit(env: Env) -> None:
    """The audit event is only for edits after the window."""
    lesson_id = await add_lesson(env.maker, env.world)

    await env.services.submit_attendance.execute(
        lesson_id=lesson_id, actor=env.admin, absent=[], base_version=0, source="staff"
    )

    assert env.outbox.audits == []


async def test_another_teacher_cannot_submit(env: Env) -> None:
    """STF-8: only the lesson's teacher or Administration."""
    lesson_id = await add_lesson(env.maker, env.world)

    with pytest.raises(NotLessonTeacherError):
        await env.services.submit_attendance.execute(
            lesson_id=lesson_id,
            actor=env.other_teacher,
            absent=[],
            base_version=0,
            source="staff",
        )


async def test_resubmit_drops_the_excuse_of_a_student_who_is_present_now(
    env: Env,
) -> None:
    """ACA-20: an excuse only exists for an absence."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id, w.bobur.id],
        base_version=0,
        source="staff",
    )
    await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=w.aziz.id,
        excused=True,
        comment="Doctor's note",
        actor=env.curator,
    )
    await env.services.set_excuse.execute(
        lesson_id=lesson_id,
        student_id=w.bobur.id,
        excused=True,
        comment=None,
        actor=env.curator,
    )

    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.bobur.id],
        base_version=3,
        source="staff",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert set((row.attendance_excused or {}).keys()) == {str(w.bobur.id)}


async def test_attendance_sheet_shows_the_saved_state_for_editing(env: Env) -> None:
    """UF-STF-06 1a: already submitted from the bot, the list opens with absences."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.camila.id],
        base_version=0,
        source="bot",
    )

    sheet = await env.services.get_attendance_sheet.execute(lesson_id, env.teacher)

    assert sheet["submitted"] is True
    assert sheet["editable"] is True
    assert sheet["submitted_by"]["last_name"] == "Kalandarova"
    assert [i["absent"] for i in sheet["roster"]] == [False, False, True]


async def test_students_who_left_the_group_stay_in_the_saved_sheet(env: Env) -> None:
    """ACA-11: statistics stay correct when groups change later."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.bobur.id],
        base_version=0,
        source="staff",
    )
    async with env.maker() as session:
        await session.execute(
            sa.update(Student)
            .where(Student.user_id == w.bobur.id)
            .values(group_id=w.other_group_id)
        )
        await session.commit()

    sheet = await env.services.get_attendance_sheet.execute(lesson_id, env.teacher)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.bobur.id],
        base_version=1,
        source="staff",
    )

    assert any(i["user_id"] == str(w.bobur.id) for i in sheet["roster"])
    row = await lesson_row(env.maker, lesson_id)
    assert w.bobur.id in (row.attendance_roster or [])
