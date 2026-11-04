"""HTTP: /v1/ai/projects (CRUD, files, chats in a project; owner-only)."""

from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.ai import ROUTERS
from app.shared.actor import Actor
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.contracts import make_file

import pytest
from httpx import AsyncClient


@pytest.fixture
def current() -> dict[str, Actor]:
    """The actor the next request runs as."""
    return {}


@pytest.fixture
async def api(
    make_harness: HarnessFactory, http_client: Any, current: dict[str, Actor]
) -> tuple[AiHarness, AsyncClient]:
    """The harness and a client whose requests run as `current["actor"]`."""
    h = make_harness()
    current["actor"] = h.student
    client = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, ai=h.services
    )
    return h, client


async def test_project_crud_follows_the_contract(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI projects: create, list, read, patch, delete."""
    _, client = api

    created = await client.post(
        "/v1/ai/projects", json={"name": "Biology", "instructions": "Be brief"}
    )
    project = created.json()
    listed = (await client.get("/v1/ai/projects")).json()
    patched = await client.patch(
        f"/v1/ai/projects/{project['id']}", json={"name": "Bio"}
    )
    deleted = await client.delete(f"/v1/ai/projects/{project['id']}")
    missing = await client.get(f"/v1/ai/projects/{project['id']}")

    assert created.status_code == 200
    assert set(project) == {"id", "name", "instructions", "created_at", "updated_at"}
    assert project["instructions"] == "Be brief"
    assert [p["id"] for p in listed] == [project["id"]]
    assert patched.json()["name"] == "Bio"
    assert patched.json()["instructions"] == "Be brief"
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["type"] == "ai/project-not-found"


async def test_another_students_project_is_not_found(
    api: tuple[AiHarness, AsyncClient], current: dict[str, Actor]
) -> None:
    """AI projects (IDOR): every route answers 404 for a project that is not yours."""
    h, client = api
    project = (await client.post("/v1/ai/projects", json={"name": "Mine"})).json()
    mine = h.files.add(make_file(h.student.user_id))
    current["actor"] = h.other_student
    pid = project["id"]

    responses = [
        await client.get(f"/v1/ai/projects/{pid}"),
        await client.patch(f"/v1/ai/projects/{pid}", json={"name": "x"}),
        await client.delete(f"/v1/ai/projects/{pid}"),
        await client.get(f"/v1/ai/projects/{pid}/files"),
        await client.post(
            f"/v1/ai/projects/{pid}/files", json={"file_id": str(mine.id)}
        ),
        await client.post(
            "/v1/ai/chats", json={"assistant": "student", "project_id": pid}
        ),
    ]

    assert {r.status_code for r in responses} == {404}


async def test_files_attach_list_and_detach(api: tuple[AiHarness, AsyncClient]) -> None:
    """AI projects: attach own ready files, list them, detach; others are refused."""
    h, client = api
    pid = (await client.post("/v1/ai/projects", json={"name": "Bio"})).json()["id"]
    mine = h.files.add(make_file(h.student.user_id, name="cells.pdf"))
    theirs = h.files.add(make_file(h.other_student.user_id, name="secret.pdf"))

    attached = await client.post(
        f"/v1/ai/projects/{pid}/files", json={"file_id": str(mine.id)}
    )
    refused = await client.post(
        f"/v1/ai/projects/{pid}/files", json={"file_id": str(theirs.id)}
    )
    listed = (await client.get(f"/v1/ai/projects/{pid}/files")).json()
    detached = await client.delete(f"/v1/ai/projects/{pid}/files/{mine.id}")

    assert attached.status_code == 204
    assert refused.status_code == 422
    assert refused.json()["type"] == "ai/attachment-invalid"
    assert listed == [{"file_id": str(mine.id), "name": "cells.pdf", "status": "ready"}]
    assert detached.status_code == 204
    assert (await client.get(f"/v1/ai/projects/{pid}/files")).json() == []


async def test_chats_can_live_in_a_project_and_be_listed_by_it(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """AI projects: a chat is created in a project and the chat list filters by it."""
    _, client = api
    pid = (await client.post("/v1/ai/projects", json={"name": "Bio"})).json()["id"]

    inside = await client.post(
        "/v1/ai/chats", json={"assistant": "student", "project_id": pid}
    )
    outside = await client.post("/v1/ai/chats", json={"assistant": "student"})
    listed = await client.get(
        "/v1/ai/chats", params={"assistant": "student", "project_id": pid}
    )

    assert inside.json()["project_id"] == pid
    assert outside.json()["project_id"] is None
    ids = [item["id"] for item in listed.json()["items"]]
    assert ids == [inside.json()["id"]]
    assert UUID(ids[0])
