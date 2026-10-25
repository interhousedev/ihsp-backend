"""POST /v1/admin/sync/runs/{run_id}/stop: ask a running sync run to stop."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Response


async def stop_run(
    run_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Stop a running sync run; 202, 404 unknown run, 409 not running."""
    await container.academic.marks.stop_sync_run.execute(actor, run_id)
    return Response(status_code=202)
