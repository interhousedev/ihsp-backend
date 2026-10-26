"""GET /v1/admin/logs/issues."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_logs.bugsink import (
    BugsinkClient,
    BugsinkUnavailableError,
    parse_datetime,
)
from app.interfaces.http.v1.admin_logs.schemas import LogIssue, LogIssuesPage, LogLevel
from app.shared.actor import Actor, Role

from fastapi import Depends, HTTPException, Query


def get_bugsink_client(
    container: Annotated[Container, Depends(get_container)],
) -> BugsinkClient | None:
    """Client when both the API URL and the token are configured."""
    cfg = container.settings.bugsink
    token = cfg.api_token.get_secret_value()
    if not cfg.api_url or not token:
        return None
    return BugsinkClient(cfg.api_url, token, _project_ids(cfg.projects, cfg.dsn))


def _project_ids(projects: list[str], dsn: str) -> list[str]:
    """Configured project ids, or the project of the DSN (its last path segment)."""
    if projects:
        return projects
    tail = dsn.rstrip("/").rsplit("/", 1)[-1] if dsn else ""
    return [tail] if tail.isdigit() else []


def _issue(client: BugsinkClient, row: dict[str, Any]) -> LogIssue:
    issue_id = str(row.get("id") or "")
    count = row.get("digested_event_count", row.get("count"))
    return LogIssue(
        id=issue_id,
        title=str(row.get("title") or ""),
        level=str(row.get("level") or LogLevel.ERROR),
        count=int(count or 0),
        last_seen=parse_datetime(row.get("last_seen")),
        project=str(row.get("project") or ""),
        url=client.deep_link(issue_id),
    )


async def list_issues(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    client: Annotated[BugsinkClient | None, Depends(get_bugsink_client)],
    project: Annotated[str | None, Query(max_length=64)] = None,
    level: Annotated[LogLevel | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LogIssuesPage:
    """Error issues from Bugsink, filtered and paged; disabled when unconfigured."""
    projects = list(container.settings.bugsink.projects)
    if project is not None and projects and project not in projects:
        raise HTTPException(status_code=422, detail="unknown error-tracking project")
    if client is None:
        return LogIssuesPage(
            items=[],
            page=page,
            size=size,
            has_next=False,
            projects=projects,
            disabled=True,
        )
    try:
        rows, has_next = await client.list_issues(
            project=project, level=level, page=page, size=size
        )
    except BugsinkUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="error tracking unavailable"
        ) from exc
    return LogIssuesPage(
        items=[_issue(client, row) for row in rows],
        page=page,
        size=size,
        has_next=has_next,
        projects=projects,
        disabled=False,
    )
