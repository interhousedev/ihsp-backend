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


def _client(handler: Any) -> BugsinkClient:
    return BugsinkClient(BASE, "tok-test", transport=httpx.MockTransport(handler))


async def test_sends_bearer_token_and_filters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    rows, has_next = await _client(handler).list_issues(
        project="3", level="error", page=2, size=5
    )

    assert rows == []
    assert has_next is False
    request = seen[0]
    assert request.url.path == "/api/canonical/0/issues/"
    assert request.url.params["project"] == "3"
    assert request.url.params["level"] == "error"
    assert request.url.params["page"] == "2"
    assert request.url.params["per_page"] == "5"
    assert request.headers["authorization"] == "Bearer tok-test"


async def test_paginated_body_reports_next_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"id": "a"}], "next": "https://x/next"}
        )

    rows, has_next = await _client(handler).list_issues(
        project=None, level=None, page=1, size=20
    )

    assert rows == [{"id": "a"}]
    assert has_next is True


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
