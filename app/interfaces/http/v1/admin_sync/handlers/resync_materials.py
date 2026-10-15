"""POST /v1/admin/sync/materials."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_sync.schemas import ResyncMaterialsBody
from app.shared.actor import Actor, Role

from fastapi import Depends, Response


async def resync_materials(
    body: ResyncMaterialsBody,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Replace the EMIS materials of the chosen terms in the worker; answers 202."""
    await container.academic.marks.run_manual_sync.resync_materials(
        actor, [(term.academic_year, term.half) for term in body.terms]
    )
    return Response(status_code=202)
