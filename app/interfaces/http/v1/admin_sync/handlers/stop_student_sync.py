"""POST /v1/admin/sync/student-syncs/{user_id}/stop: stop one running student sync."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Response


async def stop_student_sync(
    user_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Stop a running student sync; 202, 409 when it is not running."""
    await container.academic.marks.stop_student_sync.execute(actor, user_id)
    return Response(status_code=202)
