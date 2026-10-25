"""``PUT /v1/staff/lessons/{id}/homework``: add or edit homework (STF-7)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    SetHomeworkBody,
    StaffLessonResponse,
)


async def set_homework(
    id: UUID, body: SetHomeworkBody, actor: StaffActor, container: ContainerDep
) -> StaffLessonResponse:
    """Save the homework; the due date defaults to the next lesson (ACA-10)."""
    data = await container.academic.classwork.staff_set_homework.execute(
        id, actor, body.text, body.due_date
    )
    return StaffLessonResponse.model_validate(data)
