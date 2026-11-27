"""/v1/admin/day-blocks, /v1/me/timetable/day-blocks and the head-student route."""

from types import SimpleNamespace
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_schedule import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_schedule import ROUTERS as ME_ROUTERS
from app.modules.academic.application.day_blocks.use_cases import (
    CreateDayBlock,
    DeleteDayBlock,
    GetStudentDayBlocks,
    ListDayBlocks,
    UpdateDayBlock,
)
from app.modules.academic.infrastructure.day_blocks.repository import (
    SqlDayBlockStore,
)
from app.modules.academic.wiring_day_blocks import DayBlockServices
from app.shared.actor import Actor, Role
from tests.academic.schedule.env import Env
from tests.conftest import HttpClientFactory
from tests.factories import make_actor

import pytest_asyncio
from httpx import AsyncClient

LUNCH = {
    "name": "Lunch",
    "kind": "lunch",
    "starts_at": "12:00:00",
    "ends_at": "12:40:00",
    "weekdays": [1, 2, 3, 4, 5],
    "scope": "all",
    "course": None,
    "group_ids": [],
}


@pytest_asyncio.fixture
async def client_holder(
    sql_env: Env, http_client: HttpClientFactory
) -> tuple[AsyncClient, dict[str, Actor]]:
    """Admin and student schedule routers over PostgreSQL; the caller is switchable."""
    assert sql_env.maker is not None
    store = SqlDayBlockStore(sql_env.maker)
    day_blocks = DayBlockServices(
        list_blocks=ListDayBlocks(store),
        create_block=CreateDayBlock(store),
        update_block=UpdateDayBlock(store),
        delete_block=DeleteDayBlock(store),
        student_blocks=GetStudentDayBlocks(store, sql_env.clock),
    )
    holder: dict[str, Actor] = {"actor": make_actor(Role.ADMIN)}
    client = await http_client(
        [*ADMIN_ROUTERS, *ME_ROUTERS],
        {get_actor: lambda: holder["actor"]},
        academic=SimpleNamespace(schedule=sql_env.services, day_blocks=day_blocks),
        identity=SimpleNamespace(directory=sql_env.identity),
    )
    return client, holder


async def test_admin_creates_lists_updates_and_deletes_a_block(
    client_holder: tuple[AsyncClient, dict[str, Actor]],
) -> None:
    client, _ = client_holder

    created = await client.post("/v1/admin/day-blocks", json=LUNCH)
    assert created.status_code == 201
    block = created.json()
    assert {k: block[k] for k in LUNCH} == LUNCH
    block_id = block["id"]

    listed = await client.get("/v1/admin/day-blocks")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [block_id]

    changed = {**LUNCH, "name": "Second lunch", "kind": "second_lunch"}
    changed |= {"starts_at": "13:00:00", "ends_at": "13:30:00", "weekdays": [5, 1]}
    updated = await client.put(f"/v1/admin/day-blocks/{block_id}", json=changed)
    assert updated.status_code == 200
    assert updated.json()["name"] == "Second lunch"
    assert updated.json()["weekdays"] == [1, 5]

    deleted = await client.delete(f"/v1/admin/day-blocks/{block_id}")
    assert deleted.status_code == 204
    assert (await client.get("/v1/admin/day-blocks")).json() == []
    missing = await client.delete(f"/v1/admin/day-blocks/{block_id}")
    assert missing.status_code == 404
    assert missing.json()["type"] == "academic/day-block-not-found"


async def test_a_block_that_ends_before_it_starts_is_rejected(
    client_holder: tuple[AsyncClient, dict[str, Actor]],
) -> None:
    client, _ = client_holder

    response = await client.post(
        "/v1/admin/day-blocks",
        json={**LUNCH, "starts_at": "13:00:00", "ends_at": "12:00:00"},
    )

    assert response.status_code == 422
    assert response.json()["type"] == "academic/day-block-invalid"
    assert (await client.get("/v1/admin/day-blocks")).json() == []


async def test_day_blocks_are_admin_only(
    client_holder: tuple[AsyncClient, dict[str, Actor]],
) -> None:
    client, holder = client_holder
    holder["actor"] = make_actor(Role.TEACHER)

    assert (await client.get("/v1/admin/day-blocks")).status_code == 403
    assert (await client.post("/v1/admin/day-blocks", json=LUNCH)).status_code == 403


async def test_a_student_sees_only_the_blocks_of_their_group(
    sql_env: Env, client_holder: tuple[AsyncClient, dict[str, Actor]]
) -> None:
    client, holder = client_holder
    mine = await sql_env.group("2TN2")
    other = await sql_env.group("1TN1", semester=1)
    student = await sql_env.student(mine)
    for name, group_id in (("Mine", mine.id), ("Theirs", other.id)):
        response = await client.post(
            "/v1/admin/day-blocks",
            json={
                **LUNCH,
                "name": name,
                "weekdays": [2],
                "scope": "groups",
                "group_ids": [str(group_id)],
            },
        )
        assert response.status_code == 201

    holder["actor"] = make_actor(Role.STUDENT, user_id=student.id)
    response = await client.get(
        "/v1/me/timetable/day-blocks",
        params={"from": "2026-10-05", "to": "2026-10-09"},
    )

    assert response.status_code == 200
    items = response.json()
    assert [(i["name"], i["date"]) for i in items] == [("Mine", "2026-10-06")]
    assert items[0]["starts_at"] == "12:00:00"
    assert items[0]["kind"] == "lunch"


async def test_admin_sets_and_clears_the_head_student(
    sql_env: Env, client_holder: tuple[AsyncClient, dict[str, Actor]]
) -> None:
    client, _ = client_holder
    group = await sql_env.group("2TN2")
    other = await sql_env.group("1TN1", semester=1)
    member = await sql_env.student(group)
    outsider = await sql_env.student(other, first_name="Bek", last_name="Sadikov")
    url = f"/v1/admin/groups/{group.id}/head-student"

    assert (await client.put(url, json={"student_id": str(member.id)})).status_code == (
        204
    )
    assert await _head(sql_env, group.id) == member.id

    rejected = await client.put(url, json={"student_id": str(outsider.id)})
    assert rejected.status_code == 422
    assert rejected.json()["type"] == "academic/not-group-member"
    assert await _head(sql_env, group.id) == member.id

    assert (await client.put(url, json={"student_id": None})).status_code == 204
    assert await _head(sql_env, group.id) is None


async def _head(env: Env, group_id: UUID) -> UUID | None:
    async with env.uow_factory() as uow:
        group = await uow.groups.get(group_id)
    assert group is not None
    return group.head_student_id
