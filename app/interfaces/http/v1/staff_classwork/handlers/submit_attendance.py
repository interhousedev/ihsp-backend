"""``PUT /v1/staff/lessons/{id}/attendance``: submit who was absent (ACA-11)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    AttendanceSheetResponse,
    SubmitAttendanceBody,
)


async def submit_attendance(
    id: UUID,
    body: SubmitAttendanceBody,
    actor: StaffActor,
    container: ContainerDep,
) -> AttendanceSheetResponse:
    """Save the list; 409 with the current sheet if someone changed it first."""
    data = await container.academic.classwork.submit_attendance.execute(
        lesson_id=id,
        actor=actor,
        absent=body.absent,
        late=body.late,
        present_unassigned=body.present_unassigned,
        base_version=body.base_version,
        source="staff",
    )
    return AttendanceSheetResponse.model_validate(data)
