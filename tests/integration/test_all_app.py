"""The `all` application: lifespan, health, readiness, MCP metadata, host routing."""

from app.bootstrap.http_app import build_http_app
from tests.integration.conftest import ContainerFactory

from httpx import ASGITransport, AsyncClient


async def test_all_app_starts_and_answers(make_container: ContainerFactory) -> None:
    """GEN-8: /health and /ready pass, a protected route says 401, MCP is public."""
    container = await make_container("all")
    app = build_http_app(container, process="all")

    async with app.router.lifespan_context(app):  # enters the three MCP managers
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health")).json() == {"status": "ok"}
            ready = await client.get("/ready")
            assert ready.status_code == 200, ready.text
            assert (await client.get("/v1/me/alerts")).status_code == 401
            metadata = await client.get(
                "/.well-known/oauth-protected-resource/mcp/student"
            )
            assert metadata.status_code == 200
            assert metadata.json()["authorization_servers"] == [
                container.settings.hydra.issuer
            ]


async def test_short_link_host_serves_the_slug_at_the_root(
    make_container: ContainerFactory,
) -> None:
    """SL-1: on s.ihsu.uz `/robots.txt` and `/{slug}` work without the `/s` prefix."""
    container = await make_container(
        "api", short_links="https://s.ihsu.uz", api="https://api.ihsu.uz"
    )
    app = build_http_app(container, process="api")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://s.ihsu.uz"
    ) as short_host:
        robots = await short_host.get("/robots.txt")
        assert robots.status_code == 200
        assert "Disallow: /" in robots.text
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://api.ihsu.uz"
    ) as api_host:
        assert (await api_host.get("/health")).status_code == 200


async def test_mcp_host_serves_the_servers_at_its_root(
    make_container: ContainerFactory,
) -> None:
    """MCP-1: on mcp.ihsu.uz the servers answer at `/student`, not under `/mcp`."""
    container = await make_container(
        "api", mcp="https://mcp.ihsu.uz", api="https://api.ihsu.uz"
    )
    app = build_http_app(container, process="api")

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://mcp.ihsu.uz"
        ) as client:
            denied = await client.post("/student/", json={})
            metadata = await client.get("/.well-known/oauth-protected-resource/student")

    assert denied.status_code == 401
    assert "resource_metadata" in denied.headers["www-authenticate"]
    assert metadata.json()["resource"] == "https://mcp.ihsu.uz/student"
