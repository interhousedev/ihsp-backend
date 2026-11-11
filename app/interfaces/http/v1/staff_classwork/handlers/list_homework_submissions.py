"""``GET /v1/staff/lessons/{lesson_id}/homework/submissions``."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    HomeworkSubmissionsResponse,
)


async def list_homework_submissions(
    lesson_id: UUID, actor: StaffActor, container: ContainerDep
) -> HomeworkSubmissionsResponse:
    """Return who handed the homework in, with the files."""
    data = await container.academic.classwork.list_homework_submissions.execute(
        lesson_id, actor
    )
    return HomeworkSubmissionsResponse.model_validate(data)
