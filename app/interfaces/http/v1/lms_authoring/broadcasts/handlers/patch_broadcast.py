"""PATCH /v1/staff/lms/courses/{id}/broadcasts/{bid}: edit a sent broadcast."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.lms_authoring.broadcasts.schemas import (
    CourseBroadcastPatch,
    CourseBroadcastResponse,
)
from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep

from fastapi import Depends


async def patch_broadcast(
    course_id: UUID,
    broadcast_id: UUID,
    body: CourseBroadcastPatch,
    actor: ActorDep,
    container: Annotated[Container, Depends(get_container)],
) -> CourseBroadcastResponse:
    """Change the title or text; the students' notifications update in place."""
    audience = await container.lms.learning.list_broadcast_audience.execute(
        actor, course_id
    )
    changed = await container.notify.course_broadcasts.update(
        course_id=audience.course_id,
        broadcast_id=broadcast_id,
        actor_id=actor.user_id,
        is_course_admin=audience.can_manage,
        title=body.title,
        body=body.body,
    )
    return CourseBroadcastResponse.of(changed)
