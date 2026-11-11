"""``PUT /v1/me/homework/{lesson_id}/submission``: hand in files."""

from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import (
    HomeworkSubmissionBody,
    HomeworkSubmissionResponse,
)


async def submit_homework(
    lesson_id: UUID,
    body: HomeworkSubmissionBody,
    actor: StudentActor,
    container: ContainerDep,
) -> HomeworkSubmissionResponse:
    """Save or replace the submission; after the due date it counts as late."""
    data = await container.academic.classwork.submit_homework.execute(
        lesson_id, actor, body.file_ids, body.comment
    )
    return HomeworkSubmissionResponse.model_validate(data)
