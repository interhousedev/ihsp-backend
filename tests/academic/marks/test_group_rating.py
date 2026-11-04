"""GET /v1/me/group/rating: the head student's group ranked by semester GPA."""

from app.modules.academic.application.marks.get_group_rating import rank_rows
from app.modules.academic.domain.marks.errors import NotHeadStudentError
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Actor, Role
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.test_group_progress import CURATOR, _set_roles
from tests.academic.marks.world import add_student

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _row(name: str, gpa: float | None) -> dict:
    return {"name": name, "gpa": gpa, "emis_rating": None, "rank": None, "is_me": False}


def test_equal_gpas_share_a_rank_and_missing_gpas_are_unranked() -> None:
    """Competition ranking (1, 1, 3); students without a GPA have no rank, last."""
    ranked = rank_rows(
        [
            _row("Zed", None),
            _row("Bek", 4.5),
            _row("Ali", 4.5),
            _row("Cem", 3.0),
            _row("Dan", None),
        ]
    )

    assert [(r["name"], r["rank"]) for r in ranked] == [
        ("Ali", 1),
        ("Bek", 1),
        ("Cem", 3),
        ("Dan", None),
        ("Zed", None),
    ]


async def test_only_the_head_student_gets_the_rating(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Same rule as group progress: any other student gets 403; the head sees all."""
    w = env.world
    use_case = services.get_group_rating
    newcomer = await add_student(sessionmaker_in_tx, w)
    env.identity.add(make_user(newcomer, first_name="Bek", last_name="Sadikov"))
    with pytest.raises(NotHeadStudentError):
        await use_case.for_head_student(Actor(w.user_id, frozenset({Role.STUDENT})), 3)

    await _set_roles(sessionmaker_in_tx, w.group_id, CURATOR, w.user_id)
    rows = await use_case.for_head_student(
        Actor(w.user_id, frozenset({Role.STUDENT})), 3
    )

    assert len(rows) == 2
    me = next(r for r in rows if r["is_me"])
    other = next(r for r in rows if not r["is_me"])
    assert me["rank"] is not None and me["gpa"] is not None
    assert other["gpa"] is None and other["rank"] is None
    assert set(me) == {"name", "gpa", "emis_rating", "rank", "is_me"}
