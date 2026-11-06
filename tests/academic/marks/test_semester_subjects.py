"""WEB-7, WEB-12, WEB-15: the semester pages list only the subjects of the semester."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_marks import ROUTERS as MARKS_ROUTERS
from app.modules.academic.domain.marks.read_models import ResultRow
from app.modules.academic.domain.marks.semester_subjects import semester_subject_ids
from app.modules.academic.infrastructure.orm.curriculum import GroupCurriculumSubject
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Role
from tests.academic.marks.conftest import Env
from tests.academic.marks.world import MATH_EMIS, PHYSICS_EMIS

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

OLD, NEW = uuid4(), uuid4()


def _row(subject_id: UUID, *, value: str | None = None, count: int = 0) -> ResultRow:
    return ResultRow(
        semester=3,
        subject_id=subject_id,
        value=None if value is None else Decimal(value),
        lesson_avg=None,
        midterm_avg=None,
        final_avg=None,
        emis_rating=None,
        marks_count=count,
    )


def test_a_past_subject_goes_and_a_planned_one_without_marks_stays() -> None:
    """WEB-12: the group's old subject drops; the curriculum's stays with no marks."""
    assert semester_subject_ids(
        rows=[_row(OLD)],
        planned={NEW},
        group_subjects={OLD},
        taught=set(),
        is_current=True,
    ) == {NEW}


def test_a_subject_with_a_mark_is_never_hidden() -> None:
    """WEB-12: a real mark stays even if the curriculum does not plan the subject."""
    shown = semester_subject_ids(
        rows=[_row(OLD, value="4", count=1)],
        planned={NEW},
        group_subjects=set(),
        taught=set(),
        is_current=True,
    )
    assert shown == {OLD, NEW}


def test_a_subject_with_lessons_in_the_semester_stays() -> None:
    """WEB-7: lessons in the semester's dates keep an unplanned group subject."""
    shown = semester_subject_ids(
        rows=[],
        planned={NEW},
        group_subjects={OLD},
        taught={OLD},
        is_current=True,
    )
    assert shown == {OLD, NEW}


def test_without_a_curriculum_nothing_can_be_ruled_out() -> None:
    """WEB-7: no curriculum list for the semester keeps the group's subjects."""
    assert semester_subject_ids(
        rows=[],
        planned=None,
        group_subjects={OLD},
        taught=set(),
        is_current=True,
    ) == {OLD}


def test_a_past_semester_does_not_gain_planned_subjects() -> None:
    """WEB-15: a past semester keeps its own results and adds no empty subjects."""
    assert semester_subject_ids(
        rows=[_row(NEW)],
        planned={NEW, OLD},
        group_subjects={OLD},
        taught=set(),
        is_current=False,
    ) == {NEW}


async def test_the_pages_hide_a_past_subject_and_keep_one_without_marks(
    http_client: Any,
    services: MarksServices,
    env: Env,
    make_actor: Any,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """WEB-7, WEB-12, WEB-15: semester 3 drops History and keeps Chemistry."""
    history_id, chemistry_id = uuid4(), uuid4()
    async with sessionmaker_in_tx() as session:
        session.add_all(
            [
                Subject(id=history_id, emis_subject_id=901, name={"en": "History"}),
                Subject(id=chemistry_id, emis_subject_id=902, name={"en": "Chemistry"}),
            ]
        )
        await session.flush()
        group = await session.get(Group, env.world.group_id)
        assert group is not None
        group.subject_ids = [*group.subject_ids, history_id]
        plan = [(2, 901), (3, MATH_EMIS), (3, PHYSICS_EMIS), (3, 902)]
        session.add_all(
            GroupCurriculumSubject(
                group_id=env.world.group_id,
                semester_number=number,
                emis_subject_id=emis_id,
                name={"en": str(emis_id)},
            )
            for number, emis_id in plan
        )
        await session.commit()
    client = await http_client(
        MARKS_ROUTERS,
        {get_actor: lambda: make_actor(Role.STUDENT, user_id=env.world.user_id)},
        academic=SimpleNamespace(marks=services),
    )
    expected = {"Chemistry", "Fizika", "Mathematics"}

    cards = (await client.get("/v1/me/subjects")).json()
    grades = (await client.get("/v1/me/grades")).json()
    book = (await client.get("/v1/me/record-book")).json()

    assert {card["subject"]["name"] for card in cards} == expected
    assert {row["subject"]["name"] for row in grades["rows"]} == expected
    semester = next(s for s in book["semesters"] if s["semester"] == 3)
    assert {item["subject"]["name"] for item in semester["subjects"]} == expected
