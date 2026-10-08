"""``DELETE /v1/staff/lessons/{id}/homework``: remove homework (STF-7)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import StaffLessonResponse


async def clear_homework(
    id: UUID, actor: StaffActor, container: ContainerDep
) -> StaffLessonResponse:
    """Remove the homework from the students' lists."""
    data = await container.academic.classwork.staff_clear_homework.execute(id, actor)
    return StaffLessonResponse.model_validate(data)
