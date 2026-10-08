"""WEB-18..20, UF-WEB-13: the student's homework lists, ticks and notes."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    HomeworkNoteTooLongError,
    HomeworkNotFoundError,
    LessonNotFoundError,
)
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import add_lesson, local

import pytest

FRIDAY = dt.date(2026, 10, 9)
SATURDAY = dt.date(2026, 10, 10)
MONDAY = dt.date(2026, 10, 12)


async def _homework(
    env: Env,
    given: dt.date,
    period: int,
    due: dt.date | None,
    text: str,
    **extra: Any,
) -> UUID:
    return await add_lesson(
        env.maker,
        env.world,
        day=given,
        period=period,
        homework_text=text,
        homework_due_date=due,
        homework_due_auto=False,
        **extra,
    )


async def _friday_world(env: Env) -> dict[str, UUID]:
    """Friday noon, Saturday is the next study day."""
    env.clock.set(local(FRIDAY, 12))
    await add_lesson(env.maker, env.world, day=SATURDAY, period=1)
    return {
        "sat": await _homework(env, FRIDAY, 1, SATURDAY, "due Saturday"),
        "mon": await _homework(env, FRIDAY, 2, MONDAY, "due Monday"),
        "open": await _homework(env, FRIDAY, 3, None, "no due date"),
        "overdue": await _homework(
            env, FRIDAY - dt.timedelta(days=2), 1, FRIDAY - dt.timedelta(days=1), "late"
        ),
    }


async def _texts(
    env: Env, status: Literal["upcoming", "later", "done"], who: str = "aziz"
) -> list[str]:
    actor = env.student(who)
    items = await env.services.homework_list.execute(actor, status)
    return [item["text"] for item in items]


async def test_friday_homework_is_sorted_into_upcoming_and_later(env: Env) -> None:
    """WEB-18: Upcoming is due next study day, Later is the rest."""
    await _friday_world(env)

    assert await _texts(env, "upcoming") == ["due Saturday"]
    assert await _texts(env, "later") == ["due Monday", "no due date"]
    assert await _texts(env, "done") == []


async def test_ticking_moves_an_item_to_done_and_unticking_brings_it_back(
    env: Env,
) -> None:
    """UF-WEB-13 2: ticked items move to Done."""
    lessons = await _friday_world(env)

    item = await env.services.set_homework_done.execute(
        lessons["sat"], env.student("aziz"), True
    )

    assert item["done_at"] is not None
    assert await _texts(env, "upcoming") == []
    assert await _texts(env, "done") == ["due Saturday"]

    await env.services.set_homework_done.execute(
        lessons["sat"], env.student("aziz"), False
    )
    assert await _texts(env, "upcoming") == ["due Saturday"]


async def test_ticks_are_personal(env: Env) -> None:
    """UF-WEB-13: nobody else sees ticks or notes."""
    lessons = await _friday_world(env)
    await env.services.set_homework_done.execute(
        lessons["sat"], env.student("aziz"), True
    )

    assert await _texts(env, "upcoming", "bobur") == ["due Saturday"]


async def test_note_is_saved_cleared_and_limited(env: Env) -> None:
    """WEB-20: a private note of up to 1000 characters."""
    lessons = await _friday_world(env)
    aziz = env.student("aziz")

    item = await env.services.set_homework_note.execute(
        lessons["sat"], aziz, "pages 34-36 are the hard part"
    )
    cleared = await env.services.set_homework_note.execute(lessons["sat"], aziz, "")

    assert item["note"] == "pages 34-36 are the hard part"
    assert cleared["note"] is None
    with pytest.raises(HomeworkNoteTooLongError):
        await env.services.set_homework_note.execute(lessons["sat"], aziz, "x" * 1001)


async def test_teacher_edit_shows_updated_until_the_student_touches_it(
    env: Env,
) -> None:
    """UF-WEB-13 1b: the tick and the note stay, the item shows "updated"."""
    lessons = await _friday_world(env)
    aziz = env.student("aziz")
    await env.services.set_homework_done.execute(lessons["sat"], aziz, True)
    env.clock.advance(hours=1)
    await env.services.set_homework.execute(
        lessons["sat"], env.teacher, "due Saturday, edited", None
    )

    done = (await env.services.homework_list.execute(aziz, "done"))[0]
    assert done["updated"] is True
    assert done["done_at"] is not None

    env.clock.advance(minutes=5)
    again = await env.services.set_homework_note.execute(lessons["sat"], aziz, "ok")
    assert again["updated"] is False


async def test_item_carries_subject_teacher_due_and_the_lesson_date(env: Env) -> None:
    """WEB-19: subject, task, teacher, due date and "given on"."""
    await _friday_world(env)

    item = (await env.services.homework_list.execute(env.student("aziz"), "upcoming"))[
        0
    ]

    assert item["subject"]["name"] == "Physics"
    assert item["teacher"]["last_name"] == "Kalandarova"
    assert item["due_date"] == "2026-10-10"
    assert item["given_on"] == "2026-10-09"


async def test_homework_of_other_audiences_is_not_listed_or_tickable(env: Env) -> None:
    """A student sees only homework of their own audience."""
    lessons = await _friday_world(env)

    assert await _texts(env, "upcoming", "outsider") == []
    with pytest.raises(LessonNotFoundError):
        await env.services.set_homework_done.execute(
            lessons["sat"], env.student("outsider"), True
        )


async def test_lesson_without_homework_cannot_be_ticked(env: Env) -> None:
    """There is nothing to tick."""
    env.clock.set(local(FRIDAY, 12))
    lesson_id = await add_lesson(env.maker, env.world, day=FRIDAY)

    with pytest.raises(HomeworkNotFoundError):
        await env.services.set_homework_done.execute(
            lesson_id, env.student("aziz"), True
        )


async def test_subgroup_homework_reaches_that_subgroup_and_unassigned_students(
    env: Env,
) -> None:
    """ACA-2: a student without a subgroup sees both subgroups' lessons."""
    env.clock.set(local(FRIDAY, 12))
    w = env.world
    await add_lesson(env.maker, w, day=SATURDAY, period=1)
    await _homework(
        env, FRIDAY, 1, SATURDAY, "subgroup two", audience=[f"{w.group_id}:2"]
    )

    assert await _texts(env, "upcoming", "bobur") == ["subgroup two"]
    assert await _texts(env, "upcoming", "camila") == ["subgroup two"]
    assert await _texts(env, "upcoming", "aziz") == []
