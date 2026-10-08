"""POST /v1/notifications/read-all."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor

from fastapi import Depends, Response


async def mark_all_read(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Mark every notification of the caller as read."""
    await container.notify.mark_all_read.execute(actor)
    return Response(status_code=204)
