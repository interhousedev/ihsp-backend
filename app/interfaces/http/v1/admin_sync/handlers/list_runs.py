"""GET /v1/admin/sync/runs."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role
from app.shared.pagination import Page

from fastapi import Depends, Query


async def list_runs(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[dict[str, Any]]:
    """Return EMIS sync runs, newest first."""
    page: Page[dict[str, Any]] = await container.academic.marks.list_sync_runs.execute(
        actor, cursor, limit
    )
    return page
