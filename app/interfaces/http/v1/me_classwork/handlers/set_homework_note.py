"""``PUT /v1/me/homework/{lesson_id}/note``: a private note (WEB-20)."""

from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import (
    HomeworkItemResponse,
    HomeworkNoteBody,
)


async def set_homework_note(
    lesson_id: UUID,
    body: HomeworkNoteBody,
    actor: StudentActor,
    container: ContainerDep,
) -> HomeworkItemResponse:
    """Save the note (up to 1000 characters) and return the updated item."""
    data = await container.academic.classwork.set_homework_note.execute(
        lesson_id, actor, body.note
    )
    return HomeworkItemResponse.model_validate(data)
