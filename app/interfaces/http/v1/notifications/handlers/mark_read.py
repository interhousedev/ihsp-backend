"""POST /v1/notifications/{notification_id}/read."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor

from fastapi import Depends, Response


async def mark_read(
    notification_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Mark one notification as read."""
    await container.notify.mark_read.execute(actor, notification_id)
    return Response(status_code=204)
