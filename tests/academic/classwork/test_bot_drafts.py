"""BOT-16..19, UF-BOT-08: the end-of-lesson prompt and its server-side draft."""

from app.modules.academic.domain.classwork.errors import (
    AttendanceConflictError,
    LessonReassignedError,
)
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import add_lesson, lesson_row

import pytest


def _key(lesson_id: object) -> str:
    return f"att:draft:{lesson_id}"


async def test_prompt_state_lists_the_roster_with_everyone_present(env: Env) -> None:
    """BOT-16: one button per student; students without a subgroup are separate."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, audience=[f"{w.group_id}:1"])

    state = await env.services.commands.prompt_state(lesson_id, w.teacher.id)

    assert state["lesson"].subject_name == "Physics"
    assert [(r["position"], r["name"]) for r in state["roster"]] == [
        (0, "Abdullaev Aziz"),
        (1, "Rakhimova Camila"),
    ]
    assert [r["subgroup_unset"] for r in state["roster"]] == [False, True]
    assert [r["absent"] for r in state["roster"]] == [False, False]
    assert state["attendance_submitted"] is False
    assert state["attendance_version"] == 0
    assert state["expired"] is False


async def test_toggles_are_kept_on_the_server_and_survive_a_restart(env: Env) -> None:
    """UF-BOT-08 2a: the draft is on the server, the FSM may be gone."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 1)
    state = await env.services.commands.prompt_state(lesson_id, w.teacher.id)

    assert [r["absent"] for r in state["roster"]] == [False, True, False]
    ttl = await env.redis.ttl(_key(lesson_id))
    assert 35_900 <= ttl <= 36_000  # until 23:59:59 Tashkent, 10 h from 14:00


async def test_toggling_twice_clears_the_student_again(env: Env) -> None:
    """BOT-16: a second tap removes the cross."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 0)
    state = await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 0)

    assert [r["absent"] for r in state["roster"]] == [False, False, False]


async def test_unknown_position_changes_nothing(env: Env) -> None:
    """A stale button can name a position that no longer exists."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)

    state = await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 99)

    assert [r["absent"] for r in state["roster"]] == [False, False, False]
    assert await env.redis.get(_key(lesson_id)) is None


async def test_submit_saves_exactly_the_draft_and_deletes_it(env: Env) -> None:
    """UF-BOT-08 3: Submit saves the list shown against the draft's version."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 1)

    state = await env.services.commands.submit_attendance(
        lesson_id,
        env.teacher,
        absent=None,
        from_draft=True,
        base_version=0,
        source="bot",
    )

    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_absent == [w.bobur.id]
    assert row.attendance_source == "bot"
    assert state["attendance_submitted"] is True
    assert [r["absent"] for r in state["roster"]] == [False, True, False]
    assert await env.redis.get(_key(lesson_id)) is None


async def test_everyone_present_works_without_a_draft(env: Env) -> None:
    """UF-BOT-08 2: pressing Everyone present submits an empty list."""
    lesson_id = await add_lesson(env.maker, env.world)

    await env.services.commands.submit_attendance(
        lesson_id,
        env.teacher,
        absent=[],
        from_draft=False,
        base_version=0,
        source="bot",
    )

    assert (await lesson_row(env.maker, lesson_id)).attendance_absent == []


async def test_draft_older_than_a_web_edit_is_a_conflict_and_is_dropped(
    env: Env,
) -> None:
    """UF-BOT-08 3a: attendance changed on the web after the draft started."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 1)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.aziz.id],
        base_version=0,
        source="staff",
    )

    with pytest.raises(AttendanceConflictError) as error:
        await env.services.commands.submit_attendance(
            lesson_id,
            env.teacher,
            absent=None,
            from_draft=True,
            base_version=0,
            source="bot",
        )

    assert error.value.params["current"]["version"] == 1
    assert await env.redis.get(_key(lesson_id)) is None
    row = await lesson_row(env.maker, lesson_id)
    assert row.attendance_absent == [w.aziz.id]


async def test_next_day_the_prompt_is_expired_and_toggles_are_ignored(env: Env) -> None:
    """UF-BOT-08: the next day the buttons answer "this prompt has expired"."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    env.clock.advance(hours=11)  # 01:00 in Tashkent the next day

    state = await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 0)

    assert state["expired"] is True
    assert [r["absent"] for r in state["roster"]] == [False, False, False]
    assert await env.redis.get(_key(lesson_id)) is None


async def test_another_teacher_gets_lesson_reassigned(env: Env) -> None:
    """UF-BOT-08: "this lesson was reassigned"."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, teacher_id=w.other_teacher.id)

    with pytest.raises(LessonReassignedError):
        await env.services.commands.prompt_state(lesson_id, w.teacher.id)
    with pytest.raises(LessonReassignedError):
        await env.services.commands.toggle_draft_absent(lesson_id, w.teacher.id, 0)
    with pytest.raises(LessonReassignedError):
        await env.services.commands.submit_attendance(
            lesson_id,
            env.teacher,
            absent=[],
            from_draft=False,
            base_version=0,
            source="bot",
        )


async def test_prompt_state_starts_from_the_saved_sheet(env: Env) -> None:
    """UF-BOT-08 1b: attendance already done on the web shows the saved state."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w)
    await env.services.submit_attendance.execute(
        lesson_id=lesson_id,
        actor=env.teacher,
        absent=[w.camila.id],
        base_version=0,
        source="staff",
    )

    state = await env.services.commands.prompt_state(lesson_id, w.teacher.id)

    assert state["attendance_submitted"] is True
    assert state["attendance_version"] == 1
    assert [r["absent"] for r in state["roster"]] == [False, False, True]
