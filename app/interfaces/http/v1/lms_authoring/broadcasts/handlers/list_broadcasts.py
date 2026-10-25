"""GET /v1/staff/lms/courses/{id}/broadcasts: what was sent to the students."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.lms_authoring.broadcasts.schemas import (
    CourseBroadcastResponse,
)
from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep

from fastapi import Depends


async def list_broadcasts(
    course_id: UUID,
    actor: ActorDep,
    container: Annotated[Container, Depends(get_container)],
) -> list[CourseBroadcastResponse]:
    """Return the newest broadcasts of the course; same access as sending."""
    await container.lms.learning.list_broadcast_audience.execute(actor, course_id)
    history = await container.notify.course_broadcasts.history(course_id)
    return [CourseBroadcastResponse.of(item) for item in history]
