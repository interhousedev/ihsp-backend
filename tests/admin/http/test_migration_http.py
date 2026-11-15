"""Maintenance mode at the HTTP edge, the banner API and the admin migration routes."""

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_migration import ROUTERS as MIGRATION_ROUTERS
from app.interfaces.http.v1.public_config import ROUTERS as PUBLIC_ROUTERS
from app.shared.actor import Actor
from tests.admin.migration_support import ADMIN, TEACHER, TOKEN, Rig
from tests.conftest import HttpClientFactory

import pytest
from fastapi import APIRouter
from httpx import AsyncClient

probe = APIRouter()


@probe.post("/v1/probe")
async def write_probe() -> dict[str, bool]:
    return {"ok": True}


@probe.get("/v1/probe")
async def read_probe() -> dict[str, bool]:
    return {"ok": True}


@probe.post("/v1/id/login")
async def login_probe() -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def _client(
    http_client: HttpClientFactory, rig: Rig, actor: Actor = ADMIN
) -> AsyncClient:
    return await http_client(
        [*MIGRATION_ROUTERS, *PUBLIC_ROUTERS, probe],
        overrides={get_actor: lambda: actor},
        admin=rig.admin,
    )


START = {
    "target_host": "new.example.org",
    "target_port": 22,
    "pairing_token": TOKEN,
    "target_url": "https://new.example.org",
    "otp_code": "123456",
}


async def test_writes_pass_when_idle(http_client: HttpClientFactory, rig: Rig) -> None:
    client = await _client(http_client, rig)

    assert (await client.post("/v1/probe")).status_code == 200


async def test_writes_get_503_problem_json_in_maintenance(
    http_client: HttpClientFactory, rig: Rig
) -> None:
    client = await _client(http_client, rig)
    assert (
        await client.post("/v1/admin/migration/start", json=START)
    ).status_code == 200

    blocked = await client.post("/v1/probe")

    assert blocked.status_code == 503
    assert blocked.headers["content-type"].startswith("application/problem+json")
    assert blocked.headers["retry-after"]
    assert blocked.json()["type"] == "common/maintenance"
    assert blocked.json()["message_key"] == "error-maintenance"
    assert (await client.get("/v1/probe")).status_code == 200
    assert (await client.post("/v1/id/login")).status_code == 200


async def test_banner_api_is_public_and_not_cached(
    http_client: HttpClientFactory, rig: Rig
) -> None:
    client = await _client(http_client, rig)
    idle = await client.get("/v1/public/maintenance")
    assert idle.json() == {
        "active": False,
        "since": None,
        "moved": False,
        "target_url": None,
    }

    await client.post("/v1/admin/migration/start", json=START)
    busy = await client.get("/v1/public/maintenance")

    assert busy.headers["cache-control"] == "no-store"
    assert busy.json()["active"] is True and busy.json()["target_url"] is None
    assert "new.example.org" not in busy.text.replace("target_url", "")


async def test_start_route_never_echoes_the_token(
    http_client: HttpClientFactory, rig: Rig
) -> None:
    client = await _client(http_client, rig)

    response = await client.post("/v1/admin/migration/start", json=START)

    assert response.status_code == 200
    assert TOKEN not in response.text
    assert response.json()["phase"] == "queued"
    assert [s["state"] for s in response.json()["steps"]][0] == "pending"


async def test_status_and_rollback_routes(
    http_client: HttpClientFactory, rig: Rig
) -> None:
    client = await _client(http_client, rig)
    assert (await client.get("/v1/admin/migration")).json()["phase"] == "idle"
    await client.post("/v1/admin/migration/start", json=START)

    rolled = await client.post(
        "/v1/admin/migration/rollback", json={"otp_code": "123456"}
    )

    assert rolled.status_code == 200 and rolled.json()["phase"] == "cancelling"
    # Writes stay blocked until the runner acknowledges the cancel.
    assert (await client.post("/v1/probe")).status_code == 503


async def test_second_start_is_409(http_client: HttpClientFactory, rig: Rig) -> None:
    client = await _client(http_client, rig)
    await client.post("/v1/admin/migration/start", json=START)

    again = await client.post("/v1/admin/migration/start", json=START)

    assert again.status_code == 409
    assert again.json()["type"] == "admin/migration-not-allowed"


async def test_a_teacher_is_forbidden(http_client: HttpClientFactory, rig: Rig) -> None:
    client = await _client(http_client, rig, TEACHER)

    assert (await client.get("/v1/admin/migration")).status_code == 403
    assert (
        await client.post("/v1/admin/migration/start", json=START)
    ).status_code == 403
    assert rig.store.request is None
