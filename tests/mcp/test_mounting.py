"""MCP-1, MCP-3: mounting, protected resource metadata and transport security."""

from types import SimpleNamespace
from typing import cast

from app.bootstrap.container import Container
from app.interfaces.mcp.constants import SCOPES_BY_SERVER, ServerName
from app.interfaces.mcp.endpoints import resource_url, transport_security
from app.interfaces.mcp.server import build_mcp_apps, protected_resource_routes
from app.settings import Settings
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _settings(base: Settings, *, mcp: str, env: str = "test") -> Settings:
    urls = base.urls.model_copy(update={"mcp": mcp})
    return base.model_copy(update={"urls": urls, "env": env})


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
async def test_protected_resource_metadata_is_served_at_the_host_root(
    world: World, server: ServerName
) -> None:
    """MCP-3, UF-MCP-02 step 1: a client discovers Hydra from the metadata."""
    async with world.serve() as running:
        response = await running.raw.get(
            f"/.well-known/oauth-protected-resource/mcp/{server}"
        )

    body = response.json()
    assert response.status_code == 200
    assert body["resource"] == f"http://testserver/mcp/{server}"
    assert body["authorization_servers"] == [world.settings.hydra.issuer]
    assert body["scopes_supported"] == list(SCOPES_BY_SERVER[server])
    assert body["bearer_methods_supported"] == ["header"]


async def test_metadata_is_also_served_under_mcp_for_a_proxied_host(
    world: World,
) -> None:
    """Production: mcp.ihsu.uz/<server> is proxied to /mcp/<server> of the API app."""
    settings = _settings(world.settings, mcp="https://mcp.ihsu.uz")
    app = FastAPI()
    app.router.routes.extend(protected_resource_routes(settings))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://x"
    ) as client:
        direct = await client.get("/.well-known/oauth-protected-resource/student")
        proxied = await client.get("/mcp/.well-known/oauth-protected-resource/student")

    assert direct.status_code == proxied.status_code == 200
    assert direct.json() == proxied.json()
    assert direct.json()["resource"] == "https://mcp.ihsu.uz/student"


def test_resource_url_joins_the_base_and_the_server() -> None:
    """URLS__MCP + /<server>, with or without a trailing slash."""
    base = Settings(env="test")
    assert resource_url(_settings(base, mcp="https://mcp.ihsu.uz/"), "lms") == (
        "https://mcp.ihsu.uz/lms"
    )


def test_transport_security_allows_the_configured_host_only_in_production() -> None:
    """MCP-1: production allows mcp.ihsu.uz; development also allows localhost."""
    base = Settings(env="test")
    dev = transport_security(_settings(base, mcp="https://mcp.ihsu.uz", env="dev"))
    urls = base.urls.model_copy(update={"mcp": "https://mcp.ihsu.uz"})
    prod = transport_security(Settings.model_construct(env="prod", urls=urls))

    assert prod.enable_dns_rebinding_protection
    assert prod.allowed_hosts == ["mcp.ihsu.uz", "mcp.ihsu.uz:*"]
    assert prod.allowed_origins == ["https://mcp.ihsu.uz"]
    assert "localhost:*" in dev.allowed_hosts
    assert "http://localhost:*" in dev.allowed_origins


async def test_request_with_a_foreign_host_is_rejected(world: World) -> None:
    """DNS-rebinding protection: unknown Host gives 421, unknown Origin 403."""
    token, _ = world.connector_token("student", "schedule:read")
    auth = {"authorization": f"Bearer {token}"}

    async with world.serve() as running:
        wrong_host = await running.raw.post(
            "/mcp/student/", json={}, headers={**auth, "host": "evil.example"}
        )
        wrong_origin = await running.raw.post(
            "/mcp/student/", json={}, headers={**auth, "origin": "https://evil.example"}
        )

    assert wrong_host.status_code == 421
    assert wrong_origin.status_code == 403


async def test_slashless_endpoint_redirects_to_the_endpoint(world: World) -> None:
    """The mount serves `/mcp/student/`; the slashless URL redirects there."""
    async with world.serve() as running:
        response = await running.raw.post("/mcp/student", json={})

    assert response.status_code == 307
    assert response.headers["location"].endswith("/mcp/student/")


async def test_build_mcp_apps_returns_the_three_servers_with_lifespans(
    world: World,
) -> None:
    """Produces: ("/mcp/student", app, lifespan_cm), lms, admin."""
    container = SimpleNamespace(
        settings=world.settings,
        clock=world.clock,
        rate_limiter=world.deps().rate_limiter,
        i18n=world.i18n,
        identity=SimpleNamespace(
            token_verifier=world.access, connector_verifier=world.connector
        ),
        academic=SimpleNamespace(
            schedule=SimpleNamespace(queries=world.schedule),
            classwork=SimpleNamespace(queries=world.classwork),
            marks=SimpleNamespace(queries=world.marks),
        ),
        files=SimpleNamespace(public=world.files),
        links=SimpleNamespace(public=world.links),
        flashcards=SimpleNamespace(public=world.flashcards),
        lms=SimpleNamespace(
            authoring=SimpleNamespace(
                queries=world.lms_queries, draft_commands=world.lms_commands
            )
        ),
        mcp_audit=world.audit,
        admin_tools=world.admin_tools,
    )

    apps = build_mcp_apps(cast(Container, container))

    assert [path for path, _, _ in apps] == ["/mcp/student", "/mcp/lms", "/mcp/admin"]
    for _, app, lifespan in apps:
        assert callable(app)
        assert hasattr(lifespan, "__aenter__")


def test_build_mcp_apps_refuses_to_start_without_audit_or_admin_backend(
    world: World,
) -> None:
    """Security: no unaudited Administration server."""
    container = SimpleNamespace(settings=world.settings)

    with pytest.raises(ValueError, match="audit port"):
        build_mcp_apps(cast(Container, container))


async def test_a_session_works_end_to_end_over_the_mounted_app(world: World) -> None:
    """Smoke test of auth, mounting, JSON response and structured output together."""
    token, _ = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        result = await call(session, "get_schedule", date_from="2026-10-06")

    assert data_of(result)["date_to"] == "2026-10-12"
