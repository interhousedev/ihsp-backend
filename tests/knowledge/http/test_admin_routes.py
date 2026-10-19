"""HTTP: /v1/admin/knowledge is for administrators only and follows the contract."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_knowledge import ROUTERS
from app.shared.actor import Actor, Role
from tests.knowledge.conftest import KnowledgeHarness

import pytest
from httpx import AsyncClient

ENTRY_KEYS = {
    "id", "key", "title", "value", "tags", "author_id", "created_at", "updated_at",
    "score",
}  # fmt: skip


class Api:
    """A client whose requests run as ``actor``."""

    def __init__(self, client: AsyncClient, actor: Actor) -> None:
        """Start as ``actor``."""
        self.client = client
        self.actor = actor


@pytest.fixture
async def api(fake_h: KnowledgeHarness, http_client: Any) -> Api:
    """A client for the routes; ``api.actor`` decides who calls."""
    holder: dict[str, Api] = {}
    client = await http_client(
        ROUTERS, {get_actor: lambda: holder["api"].actor}, knowledge=fake_h.services
    )
    holder["api"] = Api(client, fake_h.admin)
    return holder["api"]


async def test_admin_creates_reads_lists_updates_and_deletes(api: Api) -> None:
    """KB-04: the whole life of an entry, 409 on a duplicate key, 204 on delete."""
    created = await api.client.post(
        "/v1/admin/knowledge",
        json={"key": "Library", "value": "Open 9-18", "tags": ["Rules"]},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert set(body) == ENTRY_KEYS
    assert body["key"] == "library"
    assert body["score"] is None

    duplicate = await api.client.post(
        "/v1/admin/knowledge", json={"key": "LIBRARY", "value": "x"}
    )
    assert duplicate.status_code == 409
    assert duplicate.headers["content-type"].startswith("application/problem+json")

    path = f"/v1/admin/knowledge/{body['id']}"
    assert (await api.client.get(path)).json()["value"] == "Open 9-18"
    patched = await api.client.patch(path, json={"value": "Open 9-20"})
    assert patched.json()["value"] == "Open 9-20"
    assert patched.json()["tags"] == ["rules"]

    listing = await api.client.get("/v1/admin/knowledge", params={"q": "library"})
    page = listing.json()
    assert set(page) == {"items", "total", "limit", "offset"}
    assert page["items"][0]["score"] > 0

    assert (await api.client.delete(path)).status_code == 204
    assert (await api.client.get(path)).status_code == 404


async def test_non_admin_gets_403(api: Api, fake_h: KnowledgeHarness) -> None:
    """KB-04: students and teachers cannot touch the knowledge base."""
    for role in (Role.STUDENT, Role.TEACHER):
        api.actor = Actor(user_id=fake_h.admin.user_id, roles=frozenset({role}))
        assert (await api.client.get("/v1/admin/knowledge")).status_code == 403
        post = await api.client.post(
            "/v1/admin/knowledge", json={"key": "k", "value": "v"}
        )
        assert post.status_code == 403
