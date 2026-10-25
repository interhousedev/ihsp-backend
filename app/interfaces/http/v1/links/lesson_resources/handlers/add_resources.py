"""POST /v1/lessons/{lesson_id}/resources."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.lesson_resources.schemas import AddResourceBody
from app.interfaces.http.v1.links.schemas import ResourceItem, resource_item
from app.modules.links.domain.link import LessonRole, LinkKind
from app.shared.actor import Actor

from fastapi import Depends


async def add_resources(
    lesson_id: UUID,
    body: AddResourceBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> list[ResourceItem]:
    """Attach a link or file to the lesson and to `also_lesson_ids` (ACA-9)."""
    views = await container.links.add_lesson_resources.execute(
        actor,
        lesson_id,
        role=LessonRole(body.role),
        kind=LinkKind(body.kind),
        target_url=body.target_url,
        file_id=body.file_id,
        also_lesson_ids=body.also_lesson_ids,
    )
    return [resource_item(view) for view in views]
