"""ACA-10, ACA-21, STF-7: homework, due dates and the topic."""

import datetime as dt

from app.modules.academic.domain.classwork.errors import (
    HomeworkTextError,
    NotLessonTeacherError,
)
from app.modules.academic.infrastructure.orm.lesson import Lesson
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, lesson_row

import pytest
import sqlalchemy as sa

NEXT_WEEK = DAY + dt.timedelta(days=7)


async def test_due_date_is_the_next_lesson_of_the_subject_for_the_audience(
    env: Env,
) -> None:
    """ACA-10: automatic due date, other subjects do not count."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY, period=1)
    await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=1), subject_id=w.math_id)
    await add_lesson(env.maker, w, day=NEXT_WEEK)

    lesson = await env.services.set_homework.execute(
        given, env.teacher, "Read page 5", None
    )

    assert lesson.homework_text == "Read page 5"
    assert lesson.homework_due_date == NEXT_WEEK
    assert lesson.homework_due_auto is True
    assert lesson.homework_updated_at is None  # first save is not an "update"


async def test_a_subgroup_lesson_counts_for_a_whole_group_homework(env: Env) -> None:
    """ACA-6: a whole-group lesson shares students with its subgroup lessons."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY, period=1)
    await add_lesson(env.maker, w, day=NEXT_WEEK, audience=[f"{w.group_id}:2"])

    lesson = await env.services.set_homework.execute(given, env.teacher, "Task", None)

    assert lesson.homework_due_date == NEXT_WEEK


async def test_cancelled_lessons_and_other_groups_are_not_due_dates(env: Env) -> None:
    """ACA-10: the next scheduled lesson for the same audience."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY, period=1)
    await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=2), status="cancelled")
    await add_lesson(
        env.maker, w, day=DAY + dt.timedelta(days=3), audience=[str(w.other_group_id)]
    )

    lesson = await env.services.set_homework.execute(given, env.teacher, "Task", None)

    assert lesson.homework_due_date is None  # end of term: the teacher picks a date
    assert lesson.homework_due_auto is True


async def test_teacher_can_set_the_due_date_and_it_stays_manual(env: Env) -> None:
    """ACA-10: the teacher can change the due date."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY, period=1)
    await add_lesson(env.maker, w, day=NEXT_WEEK)
    picked = DAY + dt.timedelta(days=3)

    lesson = await env.services.set_homework.execute(given, env.teacher, "Task", picked)

    assert lesson.homework_due_date == picked
    assert lesson.homework_due_auto is False


async def test_editing_the_text_sets_the_updated_badge_time(env: Env) -> None:
    """UF-STF-05 4: students see "updated" after the text changed."""
    given = await add_lesson(env.maker, env.world, day=DAY)
    await env.services.set_homework.execute(given, env.teacher, "Version one", None)
    env.clock.advance(hours=1)

    same = await env.services.set_homework.execute(
        given, env.teacher, "Version one", None
    )
    env.clock.advance(hours=1)
    edited = await env.services.set_homework.execute(
        given, env.teacher, "Version two", None
    )

    assert same.homework_updated_at is None
    assert edited.homework_updated_at == env.clock.now()
    assert edited.homework_text == "Version two"


async def test_clear_homework_removes_it_from_the_lesson(env: Env) -> None:
    """UF-STF-05 4: deleting removes it from the lists."""
    given = await add_lesson(env.maker, env.world, day=DAY)
    await env.services.set_homework.execute(given, env.teacher, "Task", None)

    lesson = await env.services.clear_homework.execute(given, env.teacher)

    assert lesson.homework_text is None
    assert lesson.homework_due_date is None
    assert lesson.has_homework is False


async def test_empty_homework_text_is_refused(env: Env) -> None:
    """ACA-10: homework is text."""
    given = await add_lesson(env.maker, env.world, day=DAY)

    with pytest.raises(HomeworkTextError):
        await env.services.set_homework.execute(given, env.teacher, "  ", None)


async def test_other_teachers_cannot_change_the_homework_but_admin_can(
    env: Env,
) -> None:
    """STF-7: the lesson's teacher or Administration."""
    given = await add_lesson(env.maker, env.world, day=DAY)

    with pytest.raises(NotLessonTeacherError):
        await env.services.set_homework.execute(given, env.other_teacher, "Task", None)
    lesson = await env.services.set_homework.execute(given, env.admin, "Task", None)

    assert lesson.homework_text == "Task"
    assert lesson.homework_due_date is None


async def test_topic_is_set_and_cleared_by_the_teacher(env: Env) -> None:
    """ACA-21: the lesson's teacher sets the topic."""
    given = await add_lesson(env.maker, env.world, day=DAY)

    set_ = await env.services.set_topic.execute(given, env.teacher, "  Waves  ")
    cleared = await env.services.set_topic.execute(given, env.teacher, " ")

    assert set_.topic == "Waves"
    assert cleared.topic is None
    with pytest.raises(NotLessonTeacherError):
        await env.services.set_topic.execute(given, env.other_teacher, "Hijack")


async def test_cancelling_the_next_lesson_moves_the_automatic_due_date(
    env: Env,
) -> None:
    """UF-SYS-05 4: recomputed when lessons are moved or cancelled."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY)
    soon = await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=2))
    await add_lesson(env.maker, w, day=NEXT_WEEK)
    await env.services.set_homework.execute(given, env.teacher, "Task", None)
    async with env.maker() as session:
        await session.execute(
            sa.update(Lesson).where(Lesson.id == soon).values(status="cancelled")
        )
        await session.commit()

    changed = await env.services.recompute_due_dates.execute([soon])

    assert changed == 1
    assert (await lesson_row(env.maker, given)).homework_due_date == NEXT_WEEK


async def test_a_newly_generated_lesson_pulls_the_due_date_forward(env: Env) -> None:
    """UF-SYS-05 4: a lesson generated later can become the next lesson."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY)
    await add_lesson(env.maker, w, day=NEXT_WEEK)
    await env.services.set_homework.execute(given, env.teacher, "Task", None)
    inserted = await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=3))

    changed = await env.services.recompute_due_dates.execute([inserted])

    assert changed == 1
    due = (await lesson_row(env.maker, given)).homework_due_date
    assert due == DAY + dt.timedelta(days=3)


async def test_the_due_date_skips_a_saturday_lesson_from_before(env: Env) -> None:
    """Nobody studies on a Saturday: the next lesson after Friday is on Monday."""
    w = env.world
    friday = DAY + dt.timedelta(days=3)
    given = await add_lesson(env.maker, w, day=friday)
    await add_lesson(env.maker, w, day=friday + dt.timedelta(days=1))  # Saturday
    monday = await add_lesson(env.maker, w, day=friday + dt.timedelta(days=3))

    await env.services.set_homework.execute(given, env.teacher, "Task", None)

    assert friday.isoweekday() == 5
    due = (await lesson_row(env.maker, given)).homework_due_date
    assert due == (await lesson_row(env.maker, monday)).date


async def test_recompute_leaves_manual_due_dates_alone(env: Env) -> None:
    """ACA-10: only automatic dates are recalculated."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY)
    manual = DAY + dt.timedelta(days=5)
    await env.services.set_homework.execute(given, env.teacher, "Task", manual)
    inserted = await add_lesson(env.maker, w, day=DAY + dt.timedelta(days=1))

    changed = await env.services.recompute_due_dates.execute([inserted])

    assert changed == 0
    assert (await lesson_row(env.maker, given)).homework_due_date == manual
