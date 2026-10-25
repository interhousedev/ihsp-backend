"""``GET /v1/staff/lessons/{id}``: a lesson page for staff (STF-4)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import StaffLessonResponse


async def get_lesson(
    id: UUID, actor: StaffActor, container: ContainerDep
) -> StaffLessonResponse:
    """Return audience, materials, homework and the attendance sheet."""
    data = await container.academic.classwork.staff_lesson.execute(id, actor)
    return StaffLessonResponse.model_validate(data)
