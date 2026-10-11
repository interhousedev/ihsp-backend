"""HTTP base: health, error mapping, CORS, dependencies."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.http.dependencies import (
    get_actor,
    get_client_ip,
    get_optional_actor,
    require_roles,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import (
    ConflictError,
    RateLimitedError,
    UnauthorizedError,
)
from app.shared.contracts.auth import AUDIENCE_API
from tests.conftest import HttpClientFactory

import pytest
from fastapi import APIRouter, Depends
from pydantic import BaseModel

PROBLEM = "application/problem+json"
APP_ORIGIN = "http://localhost:3002"
SHARE_ORIGIN = "http://localhost:3006"


class Body(BaseModel):
    """Request body for the validation test."""

    name: str


def error_routes(router: APIRouter) -> None:
    """Routes that fail in different ways."""

    @router.get("/v1/conflict")
    async def conflict() -> None:
        raise ConflictError(params={"what": "lesson"})

    @router.get("/v1/limited")
    async def limited() -> None:
        raise RateLimitedError(params={"retry_after": 7})

    @router.get("/v1/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    @router.get("/v1/leaky")
    async def leaky() -> None:
        raise ConflictError(
            params={
                "what": "lesson",
                "roles": ["admin", "teacher"],
                "count": 3,
                "upstream": {"error": "connection to 10.0.0.5 refused"},
                "trace": "x" * 201,
                "exc": RuntimeError("internals"),
            }
        )

    @router.post("/v1/body")
    async def body(payload: Body) -> dict[str, str]:
        return {"name": payload.name}


def auth_routes(router: APIRouter) -> None:
    """Routes that use the authentication dependencies."""

    @router.get("/v1/me")
    async def me(actor: Annotated[Actor, Depends(get_actor)]) -> dict[str, Any]:
        return {"user_id": str(actor.user_id)}

    @router.get("/v1/maybe")
    async def maybe(
        actor: Annotated[Actor | None, Depends(get_optional_actor)],
    ) -> dict[str, bool]:
        return {"anonymous": actor is None}

    @router.get("/v1/admin-only")
    async def admin_only(
        actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    ) -> dict[str, str]:
        return {"user_id": str(actor.user_id)}

    @router.get("/v1/ip")
    async def ip(client_ip: Annotated[str | None, Depends(get_client_ip)]) -> Any:
        return {"ip": client_ip}


def cors_routes(router: APIRouter) -> None:
    """One route per CORS group."""

    @router.get("/v1/me/today")
    async def today() -> dict[str, str]:
        return {"ok": "yes"}

    @router.get("/v1/public/x")
    async def public() -> dict[str, str]:
        return {"ok": "yes"}

    @router.post("/v1/oauth/refresh")
    async def refresh() -> dict[str, str]:
        return {"ok": "yes"}


def build_router() -> APIRouter:
    """Routes that exercise the base."""
    router = APIRouter()
    error_routes(router)
    auth_routes(router)
    cors_routes(router)
    return router


class FakeIdentity:
    """Stands in for container.identity."""

    def __init__(self, actor: Actor | None) -> None:
        """Remember the actor to return."""
        self.actor = actor
        self.token_verifier = self
        self.audiences: list[str] = []

    async def verify(self, token: str, *, audience: str) -> Actor:
        """Return the actor or reject like the real verifier."""
        self.audiences.append(audience)
        if token != "good" or self.actor is None:
            raise UnauthorizedError()
        return self.actor


async def test_health_answers_ok(http_client: HttpClientFactory) -> None:
    """GET /health is the liveness probe."""
    client = await http_client([])

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_checks_database_and_redis(
    http_client: HttpClientFactory, engine: object
) -> None:
    """GET /ready pings PostgreSQL and Redis."""
    client = await http_client([])

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"db": True, "redis": True},
    }


async def test_a_domain_error_is_problem_json(http_client: HttpClientFactory) -> None:
    """GEN-8: BaseError becomes problem+json with a stable type and message key."""
    client = await http_client([build_router()])

    response = await client.get("/v1/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith(PROBLEM)
    body = response.json()
    assert body["type"] == "common/conflict"
    assert body["status"] == 409
    assert body["message_key"] == "error-conflict"
    assert body["params"] == {"what": "lesson"}
    assert "changed by someone else" in body["title"]


async def test_error_params_echo_only_short_scalars(
    http_client: HttpClientFactory,
) -> None:
    """Problem+JSON never carries nested objects, long text or exception objects."""
    client = await http_client([build_router()])

    response = await client.get("/v1/leaky")

    assert response.status_code == 409
    assert response.json()["params"] == {
        "what": "lesson",
        "roles": ["admin", "teacher"],
        "count": 3,
    }


async def test_error_params_fill_the_english_title(
    http_client: HttpClientFactory,
) -> None:
    """The title is the English message with the params filled in."""
    client = await http_client([build_router()])

    response = await client.get("/v1/limited")

    assert response.status_code == 429
    assert "7 s" in response.json()["title"]


async def test_an_unknown_route_is_problem_json(
    http_client: HttpClientFactory,
) -> None:
    """Router-level 404 uses the same format."""
    client = await http_client([])

    response = await client.get("/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["status"] == 404


async def test_invalid_body_is_a_request_validation_problem(
    http_client: HttpClientFactory,
) -> None:
    """422 with type common/request-validation and no echoed input."""
    client = await http_client([build_router()])

    response = await client.post("/v1/body", json={"name": 5, "secret": "x"})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "common/request-validation"
    assert body["errors"][0]["loc"] == ["body", "name"]
    assert "input" not in body["errors"][0]


async def test_a_crash_is_a_500_problem_without_internals_but_with_cors(
    http_client: HttpClientFactory,
) -> None:
    """GEN-8: unhandled errors hide details, carry an error_id and keep CORS headers."""
    client = await http_client([build_router()])

    response = await client.get("/v1/boom", headers={"Origin": APP_ORIGIN})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    body = response.json()
    assert body["type"] == "common/internal"
    assert UUID(body["error_id"])
    assert "secret internals" not in response.text


async def test_cookie_routes_allow_credentials_from_app_origins(
    http_client: HttpClientFactory,
) -> None:
    """Preflight of /v1/oauth/refresh from sp: credentials allowed."""
    client = await http_client([build_router()])

    response = await client.options(
        "/v1/oauth/refresh",
        headers={
            "Origin": APP_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-ihsp-client",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_other_v1_routes_allow_app_origins_without_credentials(
    http_client: HttpClientFactory,
) -> None:
    """Preflight of /v1/me/today: origin allowed, no credentials header."""
    client = await http_client([build_router()])

    response = await client.options(
        "/v1/me/today",
        headers={
            "Origin": APP_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    assert "access-control-allow-credentials" not in response.headers


async def test_public_routes_allow_only_the_share_origin(
    http_client: HttpClientFactory,
) -> None:
    """/v1/public/* is for the static share app only, without credentials."""
    client = await http_client([build_router()])

    share = await client.get("/v1/public/x", headers={"Origin": SHARE_ORIGIN})
    app = await client.get("/v1/public/x", headers={"Origin": APP_ORIGIN})

    assert share.headers["access-control-allow-origin"] == SHARE_ORIGIN
    assert "access-control-allow-credentials" not in share.headers
    assert "access-control-allow-origin" not in app.headers


async def test_routes_outside_v1_get_no_cors_headers(
    http_client: HttpClientFactory,
) -> None:
    """/health is not a browser API."""
    client = await http_client([])

    response = await client.get("/health", headers={"Origin": APP_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


async def test_get_actor_without_identity_module_is_401(
    http_client: HttpClientFactory,
) -> None:
    """Until identity is wired, protected routes answer 401 (tests override the dep)."""
    client = await http_client([build_router()])

    response = await client.get("/v1/me", headers={"Authorization": "Bearer good"})

    assert response.status_code == 401
    assert response.json()["type"] == "auth/unauthorized"


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer", "Bearer "])
async def test_get_actor_rejects_a_missing_or_malformed_header(
    http_client: HttpClientFactory,
    make_actor: Any,
    header: str | None,
) -> None:
    """Only `Authorization: Bearer <token>` is accepted."""
    identity = FakeIdentity(make_actor(Role.STUDENT))
    client = await http_client([build_router()], identity=identity)

    response = await client.get(
        "/v1/me", headers={"Authorization": header} if header else {}
    )

    assert response.status_code == 401
    assert identity.audiences == []


async def test_get_actor_verifies_the_token_for_the_api_audience(
    http_client: HttpClientFactory, make_actor: Any
) -> None:
    """The bearer token is checked against audience ihsp-api."""
    actor = make_actor(Role.STUDENT)
    identity = FakeIdentity(actor)
    client = await http_client([build_router()], identity=identity)

    ok = await client.get("/v1/me", headers={"Authorization": "Bearer good"})
    bad = await client.get("/v1/me", headers={"Authorization": "Bearer evil"})

    assert ok.json() == {"user_id": str(actor.user_id)}
    assert bad.status_code == 401
    assert identity.audiences == [AUDIENCE_API, AUDIENCE_API]


async def test_optional_actor_is_none_without_a_header(
    http_client: HttpClientFactory,
) -> None:
    """Public pages work for anonymous visitors."""
    client = await http_client([build_router()])

    response = await client.get("/v1/maybe")

    assert response.json() == {"anonymous": True}


async def test_require_roles_allows_the_role_and_forbids_others(
    http_client: HttpClientFactory, make_actor: Any
) -> None:
    """403 problem+json for a missing role."""
    admin = FakeIdentity(make_actor(Role.ADMIN))
    student = FakeIdentity(make_actor(Role.STUDENT))
    auth = {"Authorization": "Bearer good"}

    allowed = await (await http_client([build_router()], identity=admin)).get(
        "/v1/admin-only", headers=auth
    )
    denied = await (await http_client([build_router()], identity=student)).get(
        "/v1/admin-only", headers=auth
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["type"] == "common/forbidden"
    assert denied.json()["params"] == {"roles": ["admin"]}


async def test_dependency_overrides_replace_get_actor(
    http_client: HttpClientFactory, make_actor: Any
) -> None:
    """Module tests override get_actor instead of wiring identity."""
    actor = make_actor(Role.TEACHER)

    async def fake_actor() -> Actor:
        return actor

    client = await http_client([build_router()], {get_actor: fake_actor})

    response = await client.get("/v1/me")

    assert response.json() == {"user_id": str(actor.user_id)}


async def test_get_client_ip_returns_the_peer_address(
    http_client: HttpClientFactory,
) -> None:
    """The IP comes from the ASGI client (uvicorn applies trusted proxies)."""
    client = await http_client([build_router()])

    response = await client.get("/v1/ip")

    assert response.json() == {"ip": "127.0.0.1"}
