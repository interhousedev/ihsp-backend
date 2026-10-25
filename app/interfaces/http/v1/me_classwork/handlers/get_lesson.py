"""``GET /v1/me/lessons/{id}``: a lesson page for a student of its audience."""

from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import StudentLessonResponse


async def get_lesson(
    id: UUID, actor: StudentActor, container: ContainerDep
) -> StudentLessonResponse:
    """Return materials, homework, the student's mark and attendance."""
    data = await container.academic.classwork.student_lesson.execute(id, actor)
    return StudentLessonResponse.model_validate(data)
