"""``PUT /v1/me/homework/{lesson_id}/done``: tick or untick (WEB-19)."""

from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import (
    HomeworkDoneBody,
    HomeworkItemResponse,
)


async def set_homework_done(
    lesson_id: UUID,
    body: HomeworkDoneBody,
    actor: StudentActor,
    container: ContainerDep,
) -> HomeworkItemResponse:
    """Save the tick and return the updated item."""
    data = await container.academic.classwork.set_homework_done.execute(
        lesson_id, actor, body.done
    )
    return HomeworkItemResponse.model_validate(data)
