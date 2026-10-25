"""GET /v1/admin/students/{user_id}/sync."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_sync.schemas import SyncStatusResponse
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_sync(
    user_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> SyncStatusResponse | None:
    """The student's last sync, or null when there is none."""
    job = await container.academic.emis_import.admin_get_student_sync.execute(
        actor, user_id
    )
    return SyncStatusResponse.of(job) if job else None
