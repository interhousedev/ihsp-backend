"""HTTP: GET/PUT /v1/me/dashboard."""

from typing import Any
from uuid import uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.dashboard import ROUTERS
from app.modules.dashboard.wiring import DashboardServices
from app.shared.actor import Actor, Role

import pytest
from httpx import AsyncClient


@pytest.fixture
async def client(
    dashboard: DashboardServices,
    http_client: Any,
    make_actor: Any,
) -> AsyncClient:
    """A client acting as a student."""
    actor: Actor = make_actor(Role.STUDENT)
    result: AsyncClient = await http_client(
        ROUTERS, {get_actor: lambda: actor}, dashboard=dashboard
    )
    return result


def body(kind: str = "timetable", size: str = "2x2", **extra: Any) -> dict[str, Any]:
    """A widget body."""
    return {"id": str(uuid4()), "kind": kind, "size": size, "x": 0, "y": 0, **extra}


async def test_get_returns_the_default_layout(client: AsyncClient) -> None:
    """A new user sees version 0 and the default widgets."""
    response = await client.get("/v1/me/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 0 and len(data["widgets"]) > 0


async def test_put_saves_and_returns_text_color(client: AsyncClient) -> None:
    """The saved layout comes back with version 1 and the contrast text colour."""
    response = await client.put(
        "/v1/me/dashboard",
        json={"version": 0, "widgets": [body(color="#000000")]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 1
    assert data["widgets"][0]["text_color"] == "#FFFFFF"
    again = await client.get("/v1/me/dashboard")
    assert again.json()["version"] == 1


async def test_put_with_stale_version_conflicts(client: AsyncClient) -> None:
    """A second save with version 0 answers 409."""
    first = await client.put("/v1/me/dashboard", json={"version": 0, "widgets": []})
    assert first.status_code == 200

    stale = await client.put("/v1/me/dashboard", json={"version": 0, "widgets": []})

    assert stale.status_code == 409
    assert stale.json()["type"] == "dashboard/version-conflict"


async def test_put_rejects_a_size_the_kind_does_not_allow(client: AsyncClient) -> None:
    """422 for 1x1 timetable."""
    response = await client.put(
        "/v1/me/dashboard", json={"version": 0, "widgets": [body(size="1x1")]}
    )

    assert response.status_code == 422
