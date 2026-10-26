"""Bugsink client: request shape, paging, deep links and failure mapping."""

from typing import Any

from app.interfaces.http.v1.admin_logs.bugsink import (
    BugsinkClient,
    BugsinkUnavailableError,
    parse_datetime,
)

import httpx
import pytest

BASE = "https://bugsink.example"


def _client(handler: Any, projects: list[str] | None = None) -> BugsinkClient:
    return BugsinkClient(
        BASE, "tok-test", projects or ["1"], transport=httpx.MockTransport(handler)
    )


async def test_sends_bearer_token_and_the_numeric_project() -> None:
    """Bugsink 2.6 needs ?project=<id>; no page or per_page parameters are sent."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": [], "next": None})

    await _client(handler).list_issues(project="3", level=None, page=1, size=5)

    request = seen[0]
    assert request.headers["Authorization"] == "Bearer tok-test"
    assert request.url.path == "/api/canonical/0/issues/"
    assert dict(request.url.params) == {
        "project": "3",
        "sort": "last_seen",
        "order": "desc",
    }


async def test_follows_cursor_links_and_pages_locally() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cursor" in request.url.params:
            return httpx.Response(200, json={"results": [{"id": "c"}], "next": None})
        rows = [{"id": "a"}, {"id": "b"}]
        return httpx.Response(
            200,
            json={"results": rows, "next": f"{BASE}/api/canonical/0/issues/?cursor=x"},
        )

    rows, has_next = await _client(handler).list_issues(
        project=None, level=None, page=1, size=2
    )

    assert [row["id"] for row in rows] == ["a", "b"]
    assert has_next is True


async def test_merges_projects_newest_first_and_filters_level() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        project = request.url.params["project"]
        row = {"id": project, "level": "warning" if project == "2" else "error"}
        row["last_seen"] = f"2026-10-2{project}T00:00:00Z"
        return httpx.Response(200, json={"results": [row], "next": None})

    rows, _ = await _client(handler, ["1", "2"]).list_issues(
        project=None, level=None, page=1, size=10
    )
    errors, _ = await _client(handler, ["1", "2"]).list_issues(
        project=None, level="error", page=1, size=10
    )

    assert [row["id"] for row in rows] == ["2", "1"]
    assert [row["id"] for row in errors] == ["1"]


async def test_a_next_link_to_another_host_is_not_followed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200, json={"results": [{"id": "a"}], "next": "https://evil.example/x"}
        )

    await _client(handler).list_issues(project=None, level=None, page=1, size=20)

    assert len(calls) == 1


async def test_without_a_numeric_project_it_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(BugsinkUnavailableError):
        await BugsinkClient(
            BASE, "tok-test", [], transport=httpx.MockTransport(handler)
        ).list_issues(project=None, level=None, page=1, size=20)
    with pytest.raises(BugsinkUnavailableError):
        await _client(handler).list_issues(project="web", level=None, page=1, size=20)


async def test_non_200_and_bad_body_raise() -> None:
    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def not_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>")

    with pytest.raises(BugsinkUnavailableError):
        await _client(server_error).list_issues(
            project=None, level=None, page=1, size=20
        )
    with pytest.raises(BugsinkUnavailableError):
        await _client(not_json).list_issues(project=None, level=None, page=1, size=20)


async def test_transport_error_is_mapped() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(BugsinkUnavailableError):
        await _client(boom).list_issues(project=None, level=None, page=1, size=20)


def test_deep_link_and_datetime() -> None:
    client = BugsinkClient(BASE + "/", "tok")

    assert client.deep_link("abc") == f"{BASE}/issues/issue/abc/"
    assert parse_datetime("2026-10-01T10:00:00Z") is not None
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None
