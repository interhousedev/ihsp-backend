"""GET and PUT /v1/admin/settings."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_settings import ROUTERS
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admin.conftest import Stack
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient

FORM: dict[str, Any] = {
    "school_name": "IHSU",
    "support_contact": "help@example.org",
    "change_password_on_login": True,
    "default_language": "uz",
}


@pytest.fixture
async def client(stack: Stack, http_client: HttpClientFactory) -> AsyncClient:
    return await http_client(
        ROUTERS, overrides={get_actor: lambda: stack.actor}, admin=stack.admin
    )


async def test_get_returns_defaults_and_the_feature_flags(client: AsyncClient) -> None:
    """Nothing saved yet: defaults, plus the read-only flags."""
    response = await client.get("/v1/admin/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["school_name"] == ""
    assert body["change_password_on_login"] is False
    assert body["default_language"] == "ru"
    assert body["features"]["notebooks"] is True
    assert body["features"]["change_password_on_login"] is False


async def test_put_saves_and_get_reads_it_back(client: AsyncClient) -> None:
    """The saved values come back on the next GET."""
    put = await client.put("/v1/admin/settings", json=FORM)

    assert put.status_code == 200
    assert put.json()["school_name"] == "IHSU"
    got = (await client.get("/v1/admin/settings")).json()
    assert {key: got[key] for key in FORM} == FORM


async def test_put_rejects_a_bad_language(client: AsyncClient) -> None:
    """422 from the schema; nothing changes."""
    response = await client.put(
        "/v1/admin/settings", json={**FORM, "default_language": "de"}
    )

    assert response.status_code == 422


async def test_non_admin_is_refused(
    stack: Stack, http_client: HttpClientFactory
) -> None:
    """Teachers get 403 on both routes."""
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
    client = await http_client(
        ROUTERS, overrides={get_actor: lambda: teacher}, admin=stack.admin
    )

    assert (await client.get("/v1/admin/settings")).status_code == 403
    assert (await client.put("/v1/admin/settings", json=FORM)).status_code == 403
