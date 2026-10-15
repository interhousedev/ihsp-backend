"""POST /v1/admin/sync/materials."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_sync.schemas import ResyncMaterialsBody
from app.shared.actor import Actor, Role
from app.shared.jobs import RedisJobTracker, enqueue

from fastapi import Depends, Response


async def resync_materials(
    body: ResyncMaterialsBody,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Replace the EMIS materials of the chosen terms in the worker; answers 202."""
    terms = [(term.academic_year, term.half) for term in body.terms]
    job_id = await enqueue(
        RedisJobTracker(container.redis),
        "academic.resync_materials",
        "EMIS materials " + ", ".join(f"{year}/{half}" for year, half in terms),
        started_by=str(actor.user_id),
    )
    await container.academic.marks.run_manual_sync.resync_materials(
        actor, terms, job_id=job_id
    )
    return Response(status_code=202)
