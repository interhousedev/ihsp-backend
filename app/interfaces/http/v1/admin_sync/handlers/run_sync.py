"""POST /v1/admin/sync/run."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_sync.schemas import RunSyncBody
from app.shared.actor import Actor, Role

from fastapi import Depends, Response


async def run_sync(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    body: RunSyncBody | None = None,
) -> Response:
    """Start a manual sync run for one student or for everybody; answers 202."""
    user_id = None if body is None else body.user_id
    await container.academic.marks.run_manual_sync.execute(actor, user_id)
    return Response(status_code=202)
