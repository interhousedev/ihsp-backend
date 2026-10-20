"""``GET /v1/staff/lessons/{id}/temporary-marks``: the lesson's marks (TMP-1)."""

from uuid import UUID

from app.interfaces.http.v1.staff_temporary_marks.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_temporary_marks.schemas import (
    TemporaryMarkListResponse,
)


async def list_lesson_temporary_marks(
    id: UUID, actor: StaffActor, container: ContainerDep
) -> TemporaryMarkListResponse:
    """Return the lesson's temporary marks."""
    views = await container.academic.classwork.list_lesson_temporary_marks.execute(
        id, actor
    )
    return TemporaryMarkListResponse.model_validate(
        {"items": [view.to_json() for view in views]}
    )
