"""HTTP: no authenticated route works until the current documents are accepted."""

from types import SimpleNamespace
from typing import Annotated, Any

from app.interfaces.http.dependencies import (
    get_actor,
    get_optional_actor,
    require_roles,
)
from app.interfaces.http.v1.legal import ROUTERS
from app.interfaces.http.v1.oauth.tokens.router import router as token_routes
from app.shared.actor import Actor, Role
from tests.legal.conftest import LegalHarness

import pytest
from fastapi import APIRouter, Depends
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient

AUTH = {"Authorization": "Bearer session-token"}
ACCEPT_ALLOWED = [
    ("GET", "/v1/legal/documents"),
    ("GET", "/v1/me/legal/pending"),
    ("GET", "/v1/id/me"),
    ("GET", "/v1/id/me/sessions"),
    ("POST", "/v1/id/me/sessions/revoke-others"),
    ("POST", "/v1/me/privacy/exports"),
    ("DELETE", "/v1/me/privacy/erasure"),
    ("DELETE", "/v1/me/push-subscriptions"),
]
BLOCKED = [
    ("GET", "/v1/me/profile"),
    ("GET", "/v1/notes"),
    ("POST", "/v1/notes"),
    ("PATCH", "/v1/id/me/preferences"),
    ("GET", "/v1/admin/things"),
    ("POST", "/v1/me/push-subscriptions"),
]


class Verifier:
    """Token verifier that always returns the same actor."""

    def __init__(self, actor: Actor) -> None:
        """Store the actor."""
        self.actor = actor

    async def verify(self, token: str, *, audience: str) -> Actor:
        """Accept any token."""
        return self.actor


def _routes() -> APIRouter:
    """Stand-ins for the normal routes and for the allow-listed paths."""
    router = APIRouter()

    async def ok(actor: Annotated[Actor, Depends(get_actor)]) -> dict[str, str]:
        return {"ok": "1"}

    async def admin(
        actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    ) -> dict[str, str]:
        return {"ok": "1"}

    for method, path in ACCEPT_ALLOWED + BLOCKED:
        if path.startswith(("/v1/legal/documents", "/v1/me/legal")):
            continue
        handler = admin if path.startswith("/v1/admin") else ok
        router.add_api_route(path, handler, methods=[method])
    return router


@pytest.fixture
async def client(legal: LegalHarness, http_client: Any) -> AsyncClient:
    """Real get_actor with a fake verifier, the real legal routes, fake module."""
    identity = SimpleNamespace(token_verifier=Verifier(legal.student))
    return await http_client(
        [*ROUTERS, _routes()], identity=identity, legal=legal.services
    )


async def _call(client: AsyncClient, method: str, path: str) -> int:
    response = await client.request(method, path, headers=AUTH, json=None)
    return response.status_code


async def test_nothing_published_blocks_nothing(client: AsyncClient) -> None:
    """Without a published document there is nothing to accept."""
    for method, path in BLOCKED[:3]:
        assert await _call(client, method, path) == 200


async def test_unaccepted_user_gets_403_on_normal_routes(
    client: AsyncClient, legal: LegalHarness
) -> None:
    """GET and POST (and others) answer problem+json 403 with the kinds."""
    await legal.publish("privacy")
    await legal.publish("terms")
    for method, path in BLOCKED:
        response = await client.request(method, path, headers=AUTH)
        assert response.status_code == 403, (method, path)
        body = response.json()
        assert body["type"] == "legal/acceptance-required"
        assert body["message_key"] == "legal-acceptance-required"
        assert set(body["params"]["kinds"].split(", ")) == {"privacy", "terms"}


async def test_allow_listed_routes_work_without_consent(
    client: AsyncClient, legal: LegalHarness
) -> None:
    """Documents, accepting, own profile and sessions, privacy export and erasure."""
    await legal.publish("privacy")
    for method, path in ACCEPT_ALLOWED:
        assert await _call(client, method, path) == 200, (method, path)


async def test_accepting_restores_access(
    client: AsyncClient, legal: LegalHarness
) -> None:
    """After POST /v1/me/legal/accept every route works again."""
    await legal.publish("privacy")
    assert await _call(client, "GET", "/v1/notes") == 403
    accepted = await client.post(
        "/v1/me/legal/accept",
        headers=AUTH,
        json={"items": [{"kind": "privacy", "version": 1}]},
    )
    assert accepted.status_code == 200
    for method, path in BLOCKED[:4]:
        assert await _call(client, method, path) == 200, (method, path)


async def test_a_new_version_requires_consent_again(
    client: AsyncClient, legal: LegalHarness
) -> None:
    """Publishing version 2 blocks a user who accepted version 1."""
    await legal.publish("privacy")
    await client.post(
        "/v1/me/legal/accept",
        headers=AUTH,
        json={"items": [{"kind": "privacy", "version": 1}]},
    )
    assert await _call(client, "GET", "/v1/notes") == 200

    await legal.publish("privacy")

    assert await _call(client, "GET", "/v1/notes") == 403
    assert await _call(client, "GET", "/v1/me/legal/pending") == 200


async def test_staff_follow_the_same_rule(
    legal: LegalHarness, http_client: Any
) -> None:
    """An administrator is blocked too until they accept."""
    identity = SimpleNamespace(token_verifier=Verifier(legal.admin))
    client = await http_client(
        [*ROUTERS, _routes()], identity=identity, legal=legal.services
    )
    await legal.publish("privacy")

    assert await _call(client, "GET", "/v1/admin/things") == 403


def _uses_actor(dependant: Dependant) -> bool:
    return any(
        dep.call in (get_actor, get_optional_actor) or _uses_actor(dep)
        for dep in dependant.dependencies
    )


@pytest.mark.parametrize("path", ["/v1/oauth/refresh", "/v1/oauth/logout"])
def test_refresh_and_logout_never_reach_the_gate(path: str) -> None:
    """They read the refresh cookie, not a Bearer actor, so consent cannot block."""
    [route] = [r for r in token_routes.routes if getattr(r, "path", None) == path]
    assert isinstance(route, APIRoute)
    assert not _uses_actor(route.dependant)
