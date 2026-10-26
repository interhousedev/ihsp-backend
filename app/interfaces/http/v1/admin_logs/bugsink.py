"""Client of the Bugsink API (Sentry-compatible server), read-only, server side."""

import datetime as dt
from typing import Any

import httpx

USER_AGENT = "IHT-Backend-Logs/1.0"
TIMEOUT_SECONDS = 5.0


class BugsinkUnavailableError(Exception):
    """Bugsink did not answer with a usable issue list."""


MAX_REQUESTS_PER_PROJECT = 4
"""Cursor pages read per project for one admin page (up to 250 rows each)."""


class BugsinkClient:
    """Lists issues; the token is sent only as a bearer header, never logged.

    Bugsink 2.6 lists issues of one numeric project at a time (``?project=<id>``)
    with cursor pagination, so the client queries each configured project, follows
    ``next`` links and filters by level and pages locally.
    """

    def __init__(
        self,
        api_url: str,
        api_token: str,
        projects: list[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store origin, token and default project ids; ``transport`` is for tests."""
        self.ui_base = api_url.rstrip("/")
        self.api_url = f"{self.ui_base}/api/canonical/0"
        self.api_token = api_token
        self.projects = [p for p in (projects or []) if p.isdigit()]
        self.transport = transport

    async def list_issues(
        self,
        *,
        project: str | None,
        level: str | None,
        page: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return one page of rows, newest first, and whether another page follows."""
        projects = [project] if project else self.projects
        if not projects or not all(p.isdigit() for p in projects):
            raise BugsinkUnavailableError("project")
        wanted = page * size + 1
        rows: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT_SECONDS),
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "User-Agent": USER_AGENT,
                },
                transport=self.transport,
            ) as client:
                for project_id in projects:
                    rows += await self._project_rows(client, project_id, level, wanted)
        except httpx.HTTPError as exc:
            raise BugsinkUnavailableError("transport") from exc
        rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
        start = (page - 1) * size
        return rows[start : start + size], len(rows) > start + size

    async def _project_rows(
        self,
        client: httpx.AsyncClient,
        project_id: str,
        level: str | None,
        wanted: int,
    ) -> list[dict[str, Any]]:
        """Rows of one project, following cursor links until enough rows are read."""
        url: str | None = f"{self.api_url}/issues/"
        params: dict[str, str] | None = {
            "project": project_id,
            "sort": "last_seen",
            "order": "desc",
        }
        rows: list[dict[str, Any]] = []
        for _ in range(MAX_REQUESTS_PER_PROJECT):
            if url is None or len(rows) >= wanted:
                break
            response = await client.get(url, params=params)
            if response.status_code != 200:
                raise BugsinkUnavailableError(f"status {response.status_code}")
            batch, url = _page(response, self.ui_base)
            params = None  # the next link carries the cursor and the filters
            rows += [row for row in batch if _level_matches(row, level)]
        return rows

    def deep_link(self, issue_id: str) -> str:
        """Bugsink page of one issue."""
        return f"{self.ui_base}/issues/issue/{issue_id}/"


def _level_matches(row: dict[str, Any], level: str | None) -> bool:
    return level is None or str(row.get("level") or "error") == level


def _page(
    response: httpx.Response, origin: str
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        body = response.json()
    except ValueError as exc:
        raise BugsinkUnavailableError("json") from exc
    if not (isinstance(body, dict) and isinstance(body.get("results"), list)):
        raise BugsinkUnavailableError("shape")
    next_url = body.get("next")
    if not isinstance(next_url, str) or not next_url.startswith(f"{origin}/"):
        next_url = None  # never follow a link off the configured Bugsink host
    return _rows(body["results"]), next_url


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
