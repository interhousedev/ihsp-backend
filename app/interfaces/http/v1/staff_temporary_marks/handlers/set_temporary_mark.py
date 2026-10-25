"""``PUT /v1/staff/lessons/{id}/temporary-marks/{student_id}``: set a mark (TMP-1)."""

from uuid import UUID

from app.interfaces.http.v1.staff_temporary_marks.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_temporary_marks.schemas import (
    TemporaryMarkBody,
    TemporaryMarkResponse,
)


async def set_temporary_mark(
    id: UUID,
    student_id: UUID,
    body: TemporaryMarkBody,
    actor: StaffActor,
    container: ContainerDep,
) -> TemporaryMarkResponse:
    """Create or replace the student's temporary mark for the lesson."""
    view = await container.academic.classwork.set_temporary_mark.execute(
        id, student_id, actor, value=body.value, comment=body.comment
    )
    return TemporaryMarkResponse.model_validate(view.to_json())
