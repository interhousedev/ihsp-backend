"""GET /v1/lessons/{lesson_id}/resources."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.schemas import ResourceItem, resource_item
from app.shared.actor import Actor

from fastapi import Depends


async def list_resources(
    lesson_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> list[ResourceItem]:
    """List a lesson's materials and attachments (ACA-9)."""
    views = await container.links.list_lesson_resources.execute(actor, lesson_id)
    return [resource_item(view) for view in views]
