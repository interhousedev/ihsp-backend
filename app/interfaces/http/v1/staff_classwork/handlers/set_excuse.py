"""``PUT /v1/staff/lessons/{id}/attendance/excuse``: excuse an absence (ACA-20)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    AttendanceSheetResponse,
    ExcuseBody,
)


async def set_excuse(
    id: UUID, body: ExcuseBody, actor: StaffActor, container: ContainerDep
) -> AttendanceSheetResponse:
    """Excuse or un-excuse one student's absence."""
    data = await container.academic.classwork.set_excuse.execute(
        lesson_id=id,
        student_id=body.student_id,
        excused=body.excused,
        comment=body.comment,
        actor=actor,
    )
    return AttendanceSheetResponse.model_validate(data)
