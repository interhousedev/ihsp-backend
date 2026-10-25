"""Client of the Bugsink API (Sentry-compatible server), read-only, server side."""

import datetime as dt
from typing import Any

import httpx

USER_AGENT = "IHT-Backend-Logs/1.0"
TIMEOUT_SECONDS = 5.0


class BugsinkUnavailableError(Exception):
    """Bugsink did not answer with a usable issue list."""


class BugsinkClient:
    """Lists issues; the token is sent only as a bearer header, never logged."""

    def __init__(
        self,
        api_url: str,
        api_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store origin and token; ``transport`` lets tests avoid the network."""
        self.ui_base = api_url.rstrip("/")
        self.api_url = f"{self.ui_base}/api/canonical/0"
        self.api_token = api_token
        self.transport = transport

    async def list_issues(
        self,
        *,
        project: str | None,
        level: str | None,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return the raw rows of one page and whether another page follows."""
        params = _params(project, level, page, size)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT_SECONDS),
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "User-Agent": USER_AGENT,
                },
                transport=self.transport,
            ) as client:
                response = await client.get(f"{self.api_url}/issues/", params=params)
        except httpx.HTTPError as exc:
            raise BugsinkUnavailableError("transport") from exc
        if response.status_code != 200:
            raise BugsinkUnavailableError(f"status {response.status_code}")
        return _page(response, size)

    def deep_link(self, issue_id: str) -> str:
        """Bugsink page of one issue."""
        return f"{self.ui_base}/issues/issue/{issue_id}/"


def _params(
    project: str | None, level: str | None, page: int, size: int
) -> dict[str, str | int]:
    params: dict[str, str | int] = {"page": page, "per_page": size}
    if project:
        params["project"] = project
    if level:
        params["level"] = level
    return params


def _page(response: httpx.Response, size: int) -> tuple[list[dict[str, Any]], bool]:
    try:
        body = response.json()
    except ValueError as exc:
        raise BugsinkUnavailableError("json") from exc
    if isinstance(body, list):
        return _rows(body), len(body) >= size
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        return _rows(body["results"]), body.get("next") is not None
    raise BugsinkUnavailableError("shape")


def _rows(rows: list[Any]) -> list[dict[str, Any]]:
    if not all(isinstance(row, dict) for row in rows):
        raise BugsinkUnavailableError("row")
    return rows


def parse_datetime(value: Any) -> dt.datetime | None:
    """ISO-8601 timestamp from Bugsink, None when absent or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
