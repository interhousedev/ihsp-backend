"""GET /v1/me/sync."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_sync.schemas import SyncStatusResponse
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_sync(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> SyncStatusResponse | None:
    """The last sync, or null before the first one."""
    state = await container.academic.emis_import.get_student_sync.execute(actor)
    return SyncStatusResponse.of(state) if state else None
