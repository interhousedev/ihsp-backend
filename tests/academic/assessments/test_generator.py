"""EMIS control lessons become controls: planned in a control week, else tentative."""

import datetime as dt

from app.modules.academic.application.assessments.inputs import (
    AssessmentInput,
    StaffFilters,
)
from app.modules.academic.infrastructure.orm.term import Term
from tests.academic.assessments.conftest import Env, add_exam_lesson

D = dt.date.fromisoformat


async def _all(env: Env) -> list[dict[str, object]]:
    items = await env.services.list_staff.execute(
        env.admin(), StaffFilters(), everything=True
    )
    tentative = await env.services.list_staff.execute(
        env.admin(), StaffFilters(status="tentative"), everything=True
    )
    return [*items, *[i for i in tentative if i not in items]]


async def test_a_control_lesson_inside_a_week_is_planned_and_linked(env: Env) -> None:
    """The user: EMIS control weeks are right."""
    lesson_id = await add_exam_lesson(env, D("2026-10-21"), topic="Algebra review")

    result = await env.services.generate_suggestions.execute()

    assert result == {"lessons": 1, "created": 1, "confirmed": 0}
    (item,) = await _all(env)
    assert (item["status"], item["source"], item["control"]) == (
        "planned",
        "emis",
        "midterm_1",
    )
    assert (item["title"], item["lesson_id"]) == ("Algebra review", lesson_id)
    assert item["starts_at"] is not None
    assert item["has_date"] is True


async def test_a_control_lesson_outside_every_week_is_tentative(env: Env) -> None:
    """Outside the weeks EMIS only hints."""
    await add_exam_lesson(env, D("2026-11-10"))

    await env.services.generate_suggestions.execute()

    (item,) = await _all(env)
    assert (item["status"], item["control"]) == ("tentative", None)


async def test_a_second_run_creates_nothing(env: Env) -> None:
    """The generator is idempotent."""
    await add_exam_lesson(env, D("2026-10-21"))
    await add_exam_lesson(env, D("2026-12-15"), kind="final")

    first = await env.services.generate_suggestions.execute()
    second = await env.services.generate_suggestions.execute()

    assert first["created"] == 2
    assert second == {"lessons": 2, "created": 0, "confirmed": 0}
    assert len(await _all(env)) == 2


async def test_ordinary_lessons_are_ignored(env: Env) -> None:
    """Only the kinds midterm and final count; lecture and practice do not."""
    await add_exam_lesson(env, D("2026-10-21"), kind="lecture")
    await add_exam_lesson(env, D("2026-10-22"), kind="practice")
    await add_exam_lesson(env, D("2026-10-23"), kind="other")

    result = await env.services.generate_suggestions.execute()

    assert result["lessons"] == 0
    assert await _all(env) == []


async def test_a_double_period_is_one_control(env: Env) -> None:
    """Two lessons the same day are one control."""
    await add_exam_lesson(env, D("2026-10-21"), hour=4)
    await add_exam_lesson(env, D("2026-10-21"), hour=5)

    result = await env.services.generate_suggestions.execute()

    assert (result["lessons"], result["created"]) == (2, 1)


async def test_a_teachers_control_for_the_week_blocks_the_suggestion(env: Env) -> None:
    """The teacher already set math midterm 1; EMIS lists another day of the week."""
    await env.services.create.execute(
        env.teacher(),
        AssessmentInput(
            subject_id=env.world.math_id,
            audience=[(env.world.group_id, None)],
            kind="midterm",
            date=D("2026-10-22"),
        ),
    )
    await add_exam_lesson(env, D("2026-10-21"))

    result = await env.services.generate_suggestions.execute()

    assert result["created"] == 0


async def test_old_and_far_future_lessons_are_not_read(env: Env) -> None:
    """The window is two weeks back and four months ahead."""
    await add_exam_lesson(env, D("2026-09-01"))
    await add_exam_lesson(env, D("2027-03-01"))

    assert (await env.services.generate_suggestions.execute())["lessons"] == 0


async def test_a_suggestion_becomes_planned_when_a_week_is_set_later(env: Env) -> None:
    """Administration sets the weeks after the first read."""
    async with env.maker() as session:
        term = await session.get(Term, env.world.term_id)
        assert term is not None
        term.control_periods = {}
        await session.commit()
    await add_exam_lesson(env, D("2026-10-21"))
    await env.services.generate_suggestions.execute()
    (before,) = await _all(env)
    assert before["status"] == "tentative"

    async with env.maker() as session:
        term = await session.get(Term, env.world.term_id)
        assert term is not None
        term.control_periods = {
            "midterm_1": {"start": "2026-10-19", "end": "2026-10-24"}
        }
        await session.commit()
    result = await env.services.generate_suggestions.execute()

    assert (result["created"], result["confirmed"]) == (0, 1)
    (after,) = await _all(env)
    assert (after["status"], after["control"], after["id"]) == (
        "planned",
        "midterm_1",
        before["id"],
    )
