"""``GET /v1/staff/groups/{id}/students``: the curator's students (STF-11)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import CuratorStudentResponse


async def list_group_students(
    id: UUID, actor: StaffActor, container: ContainerDep
) -> list[CuratorStudentResponse]:
    """Return students with absence rate, GPA and attention flags."""
    data = await container.academic.classwork.curator_students.execute(actor, id)
    return [CuratorStudentResponse.model_validate(item) for item in data]
