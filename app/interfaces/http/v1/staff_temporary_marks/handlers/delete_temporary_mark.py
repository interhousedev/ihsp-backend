"""``DELETE /v1/staff/lessons/{id}/temporary-marks/{student_id}`` (TMP-1)."""

from uuid import UUID

from app.interfaces.http.v1.staff_temporary_marks.deps import ContainerDep, StaffActor


async def delete_temporary_mark(
    id: UUID, student_id: UUID, actor: StaffActor, container: ContainerDep
) -> None:
    """Delete the student's temporary mark for the lesson."""
    await container.academic.classwork.delete_temporary_mark.execute(
        id, student_id, actor
    )
