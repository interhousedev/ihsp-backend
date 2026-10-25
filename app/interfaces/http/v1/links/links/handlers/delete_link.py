"""DELETE /v1/links/{id}."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor

from fastapi import Depends, Response


async def delete_link(
    link_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Delete a short link; its ID answers 410 from now on (SL-7)."""
    await container.links.delete_link.execute(actor, link_id)
    return Response(status_code=204)
