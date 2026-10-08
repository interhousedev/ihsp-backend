"""``PUT /v1/staff/lessons/{id}/topic``: set the lesson topic (ACA-21)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    SetTopicBody,
    StaffLessonResponse,
)


async def set_topic(
    id: UUID, body: SetTopicBody, actor: StaffActor, container: ContainerDep
) -> StaffLessonResponse:
    """Save the topic."""
    data = await container.academic.classwork.staff_set_topic.execute(
        id, actor, body.topic
    )
    return StaffLessonResponse.model_validate(data)
