"""ClassworkQueries and ClassworkCommands: what the assistant and the bot call."""

import datetime as dt

from app.shared.contracts.academic import LessonRef
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, seed_attendance


async def test_subject_lessons_returns_the_students_lessons_of_one_subject(
    env: Env,
) -> None:
    """ClassworkQueries.subject_lessons: other subjects and audiences are left out."""
    w = env.world
    physics = await add_lesson(env.maker, w, day=DAY)
    await add_lesson(env.maker, w, day=DAY, period=2, subject_id=w.math_id)
    await add_lesson(env.maker, w, day=DAY, period=3, audience=[f"{w.group_id}:2"])

    lessons = await env.services.queries.subject_lessons(
        w.aziz.id, w.physics_id, None, None
    )

    assert [lesson.id for lesson in lessons] == [physics]
    assert isinstance(lessons[0], LessonRef)
    assert lessons[0].subject_name == "Physics"
    assert lessons[0].group_names == ("2TN2",)


async def test_homework_query_filters_by_done_and_by_due_date(env: Env) -> None:
    """ClassworkQueries.homework: items with the lesson, done_at and the note."""
    w = env.world
    open_ = await add_lesson(
        env.maker,
        w,
        day=DAY - dt.timedelta(days=1),
        homework_text="open",
        homework_due_date=DAY + dt.timedelta(days=1),
        homework_due_auto=False,
    )
    ticked = await add_lesson(
        env.maker,
        w,
        day=DAY - dt.timedelta(days=2),
        homework_text="ticked",
        homework_due_date=DAY + dt.timedelta(days=7),
        homework_due_auto=False,
    )
    await env.services.set_homework_done.execute(ticked, env.student("aziz"), True)
    await env.services.set_homework_note.execute(ticked, env.student("aziz"), "hard")

    everything = await env.services.queries.homework(w.aziz.id, None, None, None)
    only_open = await env.services.queries.homework(w.aziz.id, None, None, False)
    only_done = await env.services.queries.homework(w.aziz.id, None, None, True)
    this_week = await env.services.queries.homework(
        w.aziz.id, DAY, DAY + dt.timedelta(days=3), None
    )

    assert {item["lesson"].id for item in everything} == {open_, ticked}
    assert [item["lesson"].id for item in only_open] == [open_]
    assert [item["lesson"].id for item in only_done] == [ticked]
    assert only_done[0]["note"] == "hard"
    assert only_done[0]["done_at"] is not None
    assert only_open[0]["done_at"] is None
    assert [item["lesson"].id for item in this_week] == [open_]


async def test_absences_query_returns_lessons_with_the_excused_flag(env: Env) -> None:
    """ClassworkQueries.absences."""
    ids = await seed_attendance(env.maker, env.world)

    items = await env.services.queries.absences(env.world.aziz.id, None, None)

    assert [(i["lesson"].id, i["excused"]) for i in items] == [
        (ids["l2"], False),
        (ids["l1"], True),
    ]


async def test_missing_attendance_query_for_one_teacher_or_everyone(env: Env) -> None:
    """ClassworkQueries.missing_attendance."""
    ids = await seed_attendance(env.maker, env.world)
    start, end = DAY - dt.timedelta(days=7), DAY

    mine = await env.services.queries.missing_attendance(
        env.world.teacher.id, start, end
    )
    everyone = await env.services.queries.missing_attendance(None, start, end)

    assert [lesson.id for lesson in mine] == [ids["today"]]
    assert {lesson.id for lesson in everyone} == {ids["today"], ids["math"]}


async def test_commands_set_and_clear_homework_and_topic(env: Env) -> None:
    """ClassworkCommands: the bot's homework flow (BOT-17..19)."""
    lesson_id = await add_lesson(env.maker, env.world)
    due = DAY + dt.timedelta(days=2)

    saved = await env.services.commands.set_homework(
        lesson_id, env.teacher, "Read page 5", due
    )
    topic = await env.services.commands.set_topic(lesson_id, env.teacher, "Waves")
    await env.services.commands.clear_homework(lesson_id, env.teacher)

    assert saved.homework_text == "Read page 5"
    assert saved.homework_due_date == due
    assert saved.subject_name == "Physics"
    assert topic.topic == "Waves"
    state = await env.services.commands.prompt_state(lesson_id, env.world.teacher.id)
    assert state["homework_text"] is None
    assert state["lesson"].topic == "Waves"


async def test_commands_set_homework_done_for_a_student(env: Env) -> None:
    """ClassworkCommands.set_homework_done: the bot's tick button (HomeworkDoneCb)."""
    w = env.world
    lesson_id = await add_lesson(env.maker, w, homework_text="Task")

    await env.services.commands.set_homework_done(lesson_id, env.student("aziz"), True)

    items = await env.services.queries.homework(w.aziz.id, None, None, True)
    assert [item["lesson"].id for item in items] == [lesson_id]
    await env.services.commands.set_homework_done(lesson_id, env.student("aziz"), False)
    assert await env.services.queries.homework(w.aziz.id, None, None, True) == []
