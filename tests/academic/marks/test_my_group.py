"""GET /v1/me/group: the caller's group for every student, with its homeroom teacher.

Members see the homeroom teacher (curator) with the teacher's public contacts,
the head student by name, and the active members. Unassigned roles are null.
"""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_marks import ROUTERS as MARKS_ROUTERS
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import TeacherContacts, UserPreferences
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.test_group_progress import CURATOR, _set_roles
from tests.academic.marks.world import add_student

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NEWCOMER_ID = UUID(int=701)


def _student(user_id: UUID) -> Actor:
    return Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))


async def test_member_sees_homeroom_teacher_head_student_and_members(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Teacher with public contacts, head by name, members sorted, head flagged."""
    w = env.world
    newcomer = await add_student(sessionmaker_in_tx, w)
    env.identity.add(make_user(w.user_id, first_name="Aliya", last_name="Karimova"))
    env.identity.add(
        make_user(newcomer, first_name="Bek", last_name="Sadikov"),
    )
    env.identity.add(
        make_user(
            CURATOR,
            first_name="Dilnoza",
            last_name="Rakhimova",
            roles=frozenset({Role.TEACHER}),
        ),
        UserPreferences(
            contacts=TeacherContacts(telegram="dilnoza_r", office="204"),
        ),
    )
    await _set_roles(sessionmaker_in_tx, w.group_id, CURATOR, w.user_id)

    data = await services.get_my_group.execute(_student(newcomer))

    assert data["id"] == w.group_id
    assert data["name"] == "2TN2"
    assert data["size"] == 2
    assert data["is_head_student"] is False
    assert data["homeroom_teacher"] == {
        "id": CURATOR,
        "first_name": "Dilnoza",
        "last_name": "Rakhimova",
        "contacts": {
            "telegram": "dilnoza_r",
            "email": None,
            "phone": None,
            "office_hours": None,
            "office": "204",
            "note": None,
        },
    }
    assert data["head_student"] == {
        "id": w.user_id,
        "first_name": "Aliya",
        "last_name": "Karimova",
    }
    assert [m["id"] for m in data["members"]] == [w.user_id, newcomer]
    assert [m["is_head_student"] for m in data["members"]] == [True, False]
    assert [m["is_me"] for m in data["members"]] == [False, True]
    assert all(
        set(m) == {"id", "first_name", "last_name", "is_head_student", "is_me"}
        for m in data["members"]
    )


async def test_head_student_flag_is_set_for_the_head(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """The head student sees the same group and is flagged as the head."""
    w = env.world
    env.identity.add(make_user(w.user_id, first_name="Aliya", last_name="Karimova"))
    await _set_roles(sessionmaker_in_tx, w.group_id, None, w.user_id)

    data = await services.get_my_group.execute(_student(w.user_id))

    assert data["is_head_student"] is True
    assert data["homeroom_teacher"] is None
    assert data["head_student"]["id"] == w.user_id
    assert data["members"][0]["is_me"] is True
    assert data["members"][0]["is_head_student"] is True


async def test_unassigned_roles_are_null(
    services: MarksServices,
    env: Env,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """No curator and no head student: both are null, members still listed."""
    w = env.world
    env.identity.add(make_user(w.user_id, first_name="Aliya", last_name="Karimova"))
    await _set_roles(sessionmaker_in_tx, w.group_id, None, None)

    data = await services.get_my_group.execute(_student(w.user_id))

    assert data["homeroom_teacher"] is None
    assert data["head_student"] is None
    assert data["is_head_student"] is False
    assert [m["is_head_student"] for m in data["members"]] == [False]


async def test_group_endpoint_is_open_to_any_member(
    http_client: Any,
    services: MarksServices,
    env: Env,
    make_actor: Any,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """GET /v1/me/group answers 200 for a plain member; unassigned roles are null."""
    w = env.world
    env.identity.add(make_user(w.user_id, first_name="Aliya", last_name="Karimova"))
    await _set_roles(sessionmaker_in_tx, w.group_id, None, None)
    actor = make_actor(Role.STUDENT, user_id=w.user_id)
    client = await http_client(
        MARKS_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(marks=services),
    )

    response = await client.get("/v1/me/group")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "2TN2"
    assert body["size"] == 1
    assert body["homeroom_teacher"] is None
    assert body["head_student"] is None
    assert body["is_head_student"] is False
    assert body["members"][0]["is_me"] is True


async def test_student_without_a_group_is_not_found(services: MarksServices) -> None:
    """A user with no student record has no group to show."""
    with pytest.raises(StudentNotFoundError):
        await services.get_my_group.execute(_student(NEWCOMER_ID))
