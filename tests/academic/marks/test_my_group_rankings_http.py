"""GET /v1/me/group/rankings over HTTP: aggregates only, never other members."""

from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_marks import ROUTERS as MARKS_ROUTERS
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.wiring_marks import MarksServices
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.identity import make_user

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ITEM_KEYS = {
    "place",
    "group_id",
    "group_name",
    "course",
    "value",
    "members_count",
    "is_mine",
}


async def test_rankings_show_groups_but_no_member_of_another_group(
    http_client: Any,
    services: MarksServices,
    env: Env,
    make_actor: Any,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """Every scope and metric answers 200 with group aggregates; no names leak."""
    w = env.world
    other_group = Group(
        id=new_id(),
        emis_group_id=3293,
        name="2TN3",
        slug="2tn3",
        current_semester=3,
        status="active",
    )
    stranger = new_id()
    async with sessionmaker_in_tx() as session:
        session.add(other_group)
        await session.flush()
        session.add(Student(user_id=stranger, group_id=other_group.id, status="active"))
        await session.commit()
    env.identity.add(make_user(w.user_id, first_name="Aliya", last_name="Karimova"))
    env.identity.add(make_user(stranger, first_name="Zarina", last_name="Yusupova"))
    actor = make_actor(Role.STUDENT, user_id=w.user_id)
    client = await http_client(
        MARKS_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(marks=services),
    )

    for scope in ("course", "lyceum"):
        for metric in ("gpa", "attendance"):
            response = await client.get(
                "/v1/me/group/rankings", params={"scope": scope, "metric": metric}
            )
            assert response.status_code == 200
            assert "Zarina" not in response.text
            assert "Yusupova" not in response.text
            assert str(stranger) not in response.text
            items = response.json()["items"]
            assert all(set(item) == ITEM_KEYS for item in items)
            mine = [item for item in items if item["is_mine"]]
            assert all(item["group_id"] == str(w.group_id) for item in mine)

    bad = await client.get("/v1/me/group/rankings", params={"scope": "world"})
    assert bad.status_code == 422


async def test_rankings_are_for_students_only(
    http_client: Any, services: MarksServices, make_actor: Any
) -> None:
    """A teacher has no group to rank."""
    actor = make_actor(Role.TEACHER)
    client = await http_client(
        MARKS_ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(marks=services),
    )

    response = await client.get("/v1/me/group/rankings")

    assert response.status_code == 403
