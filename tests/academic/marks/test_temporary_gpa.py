"""`gpa_with_temporary`: the semester mark with temporary lesson marks counted."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_marks import ROUTERS as MARKS_ROUTERS
from app.modules.academic.infrastructure.orm.temporary_mark import TemporaryMark
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Role
from tests.academic.marks.conftest import Env
from tests.academic.marks.world import DAY

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed(
    maker: async_sessionmaker[AsyncSession], env: Env, values: list[int]
) -> None:
    w = env.world
    lessons = [w.math_lesson_1, w.math_lesson_2]
    async with maker() as session:
        for lesson_id, value in zip(lessons, values, strict=False):
            session.add(
                TemporaryMark(
                    lesson_id=lesson_id,
                    student_id=w.user_id,
                    subject_id=w.math_id,
                    date=DAY,
                    value=value,
                    comment=None,
                    author_id=w.teacher_id,
                )
            )
        await session.commit()


async def _client(
    http_client: Any, services: MarksServices, env: Env, actor: Any
) -> Any:
    return await http_client(
        MARKS_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(marks=services),
    )


async def test_me_marks_views_carry_gpa_with_temporary(
    http_client: Any,
    services: MarksServices,
    env: Env,
    make_actor: Any,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """EMIS lesson [5,4,3] + midterm [5] + temporary [2,2] -> 4.1; EMIS stays 4.5."""
    await _seed(sessionmaker_in_tx, env, [2, 2])
    w = env.world
    client = await _client(
        http_client, services, env, make_actor(Role.STUDENT, user_id=w.user_id)
    )

    cards = (await client.get("/v1/me/subjects")).json()
    physics, math = cards
    assert (math["semester_mark"], math["gpa_with_temporary"]) == (4.5, 4.1)
    assert physics["gpa_with_temporary"] is None

    detail = (await client.get(f"/v1/me/subjects/{w.math_id}")).json()
    assert (detail["semester_mark"], detail["gpa_with_temporary"]) == (4.5, 4.1)

    grades = (await client.get("/v1/me/grades?semester=3")).json()
    by_mark = {r["subject"]["id"]: r for r in grades["rows"]}
    assert by_mark[str(w.math_id)]["gpa_with_temporary"] == 4.1
    assert by_mark[str(w.physics_id)]["gpa_with_temporary"] is None

    book = (await client.get("/v1/me/record-book")).json()
    subjects = {s["subject"]["id"]: s for s in book["semesters"][0]["subjects"]}
    assert subjects[str(w.math_id)]["gpa_with_temporary"] == 4.1
    assert subjects[str(w.physics_id)]["gpa_with_temporary"] is None


async def test_summary_and_no_temporary_marks(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Null without temporary marks; the public summary carries the value."""
    uid: UUID = env.world.user_id
    before = await services.queries.subjects_summary(uid, None)
    assert [s.gpa_with_temporary for s in before] == [None, None]

    await _seed(sessionmaker_in_tx, env, [2, 2])

    after = {s.name: s for s in await services.queries.subjects_summary(uid, None)}
    assert after["Mathematics"].gpa_with_temporary == 4.1
    assert after["Fizika"].gpa_with_temporary is None
