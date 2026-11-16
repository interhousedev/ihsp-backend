"""HTTP: /v1/admission needs the admission documents even without X-IHSP-App."""

from types import SimpleNamespace
from typing import Annotated, Any

from app.interfaces.http.dependencies import get_actor
from app.shared.actor import Actor
from app.shared.contracts.legal import scopes_for_request
from tests.legal.conftest import LegalHarness

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient

AUTH = {"Authorization": "Bearer session-token"}


class Verifier:
    """Token verifier that always returns the same actor."""

    def __init__(self, actor: Actor) -> None:
        """Store the actor."""
        self.actor = actor

    async def verify(self, token: str, *, audience: str) -> Actor:
        """Accept any token."""
        return self.actor


def _routes() -> APIRouter:
    router = APIRouter()

    async def ok(actor: Annotated[Actor, Depends(get_actor)]) -> dict[str, str]:
        return {"ok": "1"}

    router.add_api_route("/v1/admission/me", ok, methods=["GET"])
    router.add_api_route("/v1/notes", ok, methods=["GET"])
    return router


@pytest.fixture
async def client(legal: LegalHarness, http_client: Any) -> AsyncClient:
    """Real get_actor with a fake verifier and the real legal module."""
    identity = SimpleNamespace(token_verifier=Verifier(legal.student))
    return await http_client([_routes()], identity=identity, legal=legal.services)


@pytest.mark.parametrize("header", [None, "sp", "bogus"])
async def test_pending_admission_document_blocks_without_app_header(
    client: AsyncClient, legal: LegalHarness, header: str | None
) -> None:
    await legal.publish("privacy", app_scope="admission")
    headers = dict(AUTH) | ({"X-IHSP-App": header} if header else {})

    blocked = await client.get("/v1/admission/me", headers=headers)
    other = await client.get("/v1/notes", headers=headers)

    assert blocked.status_code == 403
    assert blocked.json()["type"] == "legal/acceptance-required"
    assert other.status_code == 200


def test_header_only_adds_scopes() -> None:
    assert scopes_for_request("sp", "/v1/admission/me") == ("sp", "admission")
    assert scopes_for_request("admission", "/v1/admission/me") == ("admission",)
    assert scopes_for_request(None, "/v1/admissions") == ("global",)
