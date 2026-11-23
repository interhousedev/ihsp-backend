"""Graded code and HTML widgets of a live step: stored result, access, points."""

from typing import Any
from uuid import uuid4

from app.interfaces.http.v1.lms_learning.handlers.widget_result import (
    WIDGET_RESULT_LIMIT,
)
from app.modules.lms.application.learning.views import LearningCodeBlockView
from app.modules.lms.domain.learning.errors import (
    BlockNotFoundError,
    CourseNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.step_content import CodeBlock, CodeTest, HtmlBlock
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import (
    SeededCourse,
    add_staff,
    content,
    seed_course,
)

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _course(maker: async_sessionmaker[AsyncSession]) -> SeededCourse:
    code: Any = CodeBlock(
        id="c",
        graded=True,
        starter="x = 1",
        solution="x = 2",
        tests=[CodeTest(id="t", name="x is 2", code="assert x == 2", hidden=True)],
    )
    free: Any = CodeBlock(id="free")
    html: Any = HtmlBlock(id="h", graded=True)
    return await seed_course(maker, steps=[("s", content("Code", code, free, html))])


async def test_best_score_is_kept_and_shown(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    await learning.enroll_in_course.execute(student, course.id)
    record = learning.record_widget_result.execute

    assert (await record(student, course.id, step_id, "c", 100, True)).completed
    second = await record(student, course.id, step_id, "c", 10, False)
    assert second.score == 100 and second.completed
    await record(student, course.id, step_id, "h", 40, False)

    view = await learning.get_step_view.execute(student, course.id, step_id)
    code = next(b for b in view.blocks if b.id == "c")
    assert isinstance(code, LearningCodeBlockView)
    assert code.passed and code.result is not None and code.result.score == 100
    assert code.tests[0].code == "" and "solution" not in code.model_dump()
    html = next(b for b in view.blocks if b.id == "h")
    assert not html.passed


async def test_strangers_ungraded_and_foreign_course_are_rejected(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    record = learning.record_widget_result.execute
    with pytest.raises(NotEnrolledError):
        await record(student, course.id, step_id, "c", 100, True)
    await learning.enroll_in_course.execute(student, course.id)
    with pytest.raises(BlockNotFoundError):
        await record(student, course.id, step_id, "free", 100, True)
    with pytest.raises(BlockNotFoundError):
        await record(student, course.id, step_id, "missing", 100, True)
    with pytest.raises(CourseNotFoundError):
        await record(student, uuid4(), step_id, "c", 100, True)


async def test_result_route(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    url = f"/v1/lms/courses/{course.id}/steps/{step_id}/blocks/c/result"
    caller["actor"] = student

    denied = await client.post(url, json={"score_pct": 100, "passed": True})
    assert denied.status_code == 403
    await learning.enroll_in_course.execute(student, course.id)
    bad = await client.post(url, json={"score_pct": 101, "passed": True})
    assert bad.status_code == 422
    ok = await client.post(url, json={"score_pct": 75, "passed": True})
    assert ok.status_code == 200
    assert ok.json() == {
        "score": 75.0,
        "max_score": 100.0,
        "completed": True,
        "verified": False,
    }
    assert "no-store" in ok.headers["cache-control"]


async def test_hidden_tests_are_served_only_to_enrolled_students(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    base = f"/v1/lms/courses/{course.id}/steps/{step_id}/blocks"
    caller["actor"] = student

    assert (await client.post(f"{base}/c/hidden-tests")).status_code == 403
    await learning.enroll_in_course.execute(student, course.id)
    ok = await client.post(f"{base}/c/hidden-tests")
    assert ok.status_code == 200
    assert ok.json() == {
        "tests": [
            {"id": "t", "name": "x is 2", "hidden": True, "code": "assert x == 2"}
        ]
    }
    assert "no-store" in ok.headers["cache-control"]
    assert (await client.post(f"{base}/free/hidden-tests")).status_code == 404
    with pytest.raises(CourseNotFoundError):
        await learning.get_hidden_tests.execute(student, uuid4(), step_id, "c")


async def test_staff_see_unverified_widget_results(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
    teacher: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    await learning.enroll_in_course.execute(student, course.id)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    await learning.record_widget_result.execute(
        student, course.id, step_id, "c", 80, True
    )

    [row] = await learning.list_course_students.execute(teacher, course.id)

    assert [
        (w.step_id, w.block_id, w.score_pct, w.passed, w.verified)
        for w in row.widget_results
    ] == [(step_id, "c", 80.0, True, False)]


async def test_widget_points_stay_out_of_course_totals(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    await learning.enroll_in_course.execute(student, course.id)
    await learning.record_widget_result.execute(
        student, course.id, step_id, "c", 100, True
    )
    await learning.record_widget_result.execute(
        student, course.id, step_id, "h", 100, True
    )

    page = await learning.get_course_page.execute(student, course.slug)

    assert page.points_total == 0.0
    assert page.points_earned == 0.0


async def test_result_route_is_rate_limited(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    url = f"/v1/lms/courses/{course.id}/steps/{step_id}/blocks/c/result"
    caller["actor"] = student
    await learning.enroll_in_course.execute(student, course.id)

    codes = [
        (await client.post(url, json={"score_pct": 50, "passed": False})).status_code
        for _ in range(WIDGET_RESULT_LIMIT + 1)
    ]

    assert codes[:-1] == [200] * WIDGET_RESULT_LIMIT and codes[-1] == 429
