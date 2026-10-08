"""DELETE /v1/lessons/{lesson_id}/resources/{link_id}."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor

from fastapi import Depends, Response


async def delete_resource(
    lesson_id: UUID,
    link_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Delete a lesson resource (UF-WEB-08)."""
    await container.links.delete_lesson_resource.execute(actor, lesson_id, link_id)
    return Response(status_code=204)
