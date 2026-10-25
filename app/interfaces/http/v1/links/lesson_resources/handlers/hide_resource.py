"""POST /v1/lessons/{lesson_id}/resources/{link_id}/hide."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.lesson_resources.schemas import HideResourceBody
from app.interfaces.http.v1.links.schemas import ResourceItem, resource_item
from app.shared.actor import Actor

from fastapi import Depends


async def hide_resource(
    lesson_id: UUID,
    link_id: UUID,
    body: HideResourceBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> ResourceItem:
    """Hide or show a resource for students and the room page (STF-6)."""
    view = await container.links.hide_lesson_resource.execute(
        actor, lesson_id, link_id, hidden=body.hidden
    )
    return resource_item(view)
