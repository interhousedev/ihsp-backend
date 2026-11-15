"""HTTP: the user's export and erasure routes and the administrators' queue."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.privacy import ROUTERS
from app.shared.actor import Actor
from tests.privacy.conftest import PrivacyHarness

import pytest
from httpx import AsyncClient


class Api:
    """A client whose requests run as ``actor``."""

    def __init__(self, client: AsyncClient, actor: Actor) -> None:
        """Start as ``actor``."""
        self.client = client
        self.actor = actor


@pytest.fixture
async def api(privacy: PrivacyHarness, http_client: Any) -> Api:
    """The privacy routers on the fake module, as a student."""
    holder: dict[str, Api] = {}
    client = await http_client(
        ROUTERS, {get_actor: lambda: holder["api"].actor}, privacy=privacy.services
    )
    holder["api"] = Api(client, privacy.student)
    return holder["api"]


async def test_export_flow_and_idor(api: Api, privacy: PrivacyHarness) -> None:
    """202, 429 on the second request, download for the owner, 404 for others."""
    first = await api.client.post("/v1/me/privacy/exports")
    assert first.status_code == 202
    export_id = first.json()["id"]
    again = await api.client.post("/v1/me/privacy/exports")
    assert again.status_code == 429
    assert again.json()["type"] == "privacy/export-rate-limited"

    await privacy.services.build_export.execute(__import__("uuid").UUID(export_id))
    ok = await api.client.get(f"/v1/me/privacy/exports/{export_id}/download")
    assert ok.status_code == 200 and ok.json()["url"].startswith("memory://")
    assert len((await api.client.get("/v1/me/privacy/exports")).json()["items"]) == 1

    api.actor = privacy.admin
    stolen = await api.client.get(f"/v1/me/privacy/exports/{export_id}/download")
    assert stolen.status_code == 404
    assert stolen.json()["type"] == "privacy/export-not-found"


async def test_admin_queue(api: Api, privacy: PrivacyHarness) -> None:
    """403 for a student; approve once, then 409; unknown id 404."""
    ticket = await privacy.services.erasure.request(
        privacy.user_id, ip=None, user_agent=None
    )
    rid = ticket.request_id
    assert (
        await api.client.get("/v1/admin/privacy/erasure-requests")
    ).status_code == 403
    mine = (await api.client.get("/v1/me/privacy/erasure")).json()
    assert mine["request"]["status"] == "pending_review"

    api.actor = privacy.admin
    listed = await api.client.get("/v1/admin/privacy/erasure-requests")
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    ok = await api.client.post(f"/v1/admin/privacy/erasure-requests/{rid}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    twice = await api.client.post(
        f"/v1/admin/privacy/erasure-requests/{rid}/reject", json={"reason": "x"}
    )
    assert twice.status_code == 409
    assert twice.json()["type"] == "privacy/erasure-not-pending"
    unknown = await api.client.post(
        "/v1/admin/privacy/erasure-requests/"
        "00000000-0000-7000-8000-000000000000/approve"
    )
    assert unknown.status_code == 404
