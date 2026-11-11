"""``GET /v1/me/homework/{lesson_id}/submission``: the own submission."""

from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import HomeworkSubmissionResponse


async def get_homework_submission(
    lesson_id: UUID, actor: StudentActor, container: ContainerDep
) -> HomeworkSubmissionResponse:
    """Return the caller's submission or 404."""
    data = await container.academic.classwork.get_homework_submission.execute(
        lesson_id, actor
    )
    return HomeworkSubmissionResponse.model_validate(data)
