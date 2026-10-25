"""POST /v1/staff/lms/courses/{id}/broadcasts: update the enrolled students."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.lms_authoring.broadcasts.schemas import (
    CourseBroadcastBody,
    CourseBroadcastResponse,
)
from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep

from fastapi import Depends


async def send_broadcast(
    course_id: UUID,
    body: CourseBroadcastBody,
    actor: ActorDep,
    container: Annotated[Container, Depends(get_container)],
) -> CourseBroadcastResponse:
    """Notify every enrolled student (in the app, by Web Push and in Telegram)."""
    audience = await container.lms.learning.list_broadcast_audience.execute(
        actor, course_id
    )
    sent = await container.notify.course_broadcasts.send(
        course_id=audience.course_id,
        course_slug=audience.slug,
        author_id=actor.user_id,
        title=body.title,
        body=body.body,
        recipient_ids=audience.user_ids,
    )
    return CourseBroadcastResponse.of(sent.broadcast, len(sent.user_ids))
