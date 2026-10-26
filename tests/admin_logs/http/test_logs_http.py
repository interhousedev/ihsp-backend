"""GET /v1/admin/logs/issues."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_logs import ROUTERS
from app.interfaces.http.v1.admin_logs.bugsink import BugsinkClient
from app.interfaces.http.v1.admin_logs.handlers.list_issues import get_bugsink_client
from app.settings import BugsinkSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory

import httpx
from httpx import AsyncClient

ROWS: list[dict[str, Any]] = [
    {
        "id": "issue-1",
        "title": "KeyError: 'x'",
        "level": "error",
        "digested_event_count": 7,
        "last_seen": "2026-10-10T08:00:00Z",
        "project": "3",
    }
]


def _actor() -> Actor:
    return Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))


async def test_disabled_when_bugsink_is_not_configured(
    http_client: HttpClientFactory,
) -> None:
    client = await http_client(ROUTERS, overrides={get_actor: _actor})

    response = await client.get("/v1/admin/logs/issues")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["disabled"] is True


async def _enabled(http_client: HttpClientFactory, handler: Any) -> AsyncClient:
    transport = httpx.MockTransport(handler)
    return await http_client(
        ROUTERS,
        overrides={
            get_actor: _actor,
            get_bugsink_client: lambda: BugsinkClient(
                "https://bugsink.example", "tok", ["1"], transport=transport
            ),
        },
    )


async def test_maps_issues_with_deep_links(http_client: HttpClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["project"] == "1"
        return httpx.Response(200, json={"results": ROWS, "next": None})

    client = await _enabled(http_client, handler)

    response = await client.get("/v1/admin/logs/issues", params={"level": "error"})

    assert response.status_code == 200
    body = response.json()
    assert body["disabled"] is False
    assert body["has_next"] is False
    assert body["items"] == [
        {
            "id": "issue-1",
            "title": "KeyError: 'x'",
            "level": "error",
            "count": 7,
            "last_seen": "2026-10-10T08:00:00Z",
            "project": "3",
            "url": "https://bugsink.example/issues/issue/issue-1/",
        }
    ]


async def test_upstream_failure_is_502(http_client: HttpClientFactory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = await _enabled(http_client, handler)

    response = await client.get("/v1/admin/logs/issues")

    assert response.status_code == 502


async def test_rejects_a_project_outside_the_configured_ones(
    http_client: HttpClientFactory, settings: Settings
) -> None:
    configured = settings.model_copy(
        update={"bugsink": BugsinkSettings(projects=["3"])}
    )
    client = await http_client(
        ROUTERS, overrides={get_actor: _actor}, settings=configured
    )

    unknown = await client.get("/v1/admin/logs/issues", params={"project": "9"})
    known = await client.get("/v1/admin/logs/issues", params={"project": "3"})

    assert unknown.status_code == 422
    assert known.status_code == 200


async def test_rejects_unknown_level(http_client: HttpClientFactory) -> None:
    client = await _enabled(http_client, lambda r: httpx.Response(200, json=[]))

    response = await client.get("/v1/admin/logs/issues", params={"level": "loud"})

    assert response.status_code == 422
