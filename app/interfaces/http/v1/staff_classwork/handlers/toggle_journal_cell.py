"""``POST /v1/staff/journal/toggle``: toggle one absence in the grid (STF-9)."""

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, TeacherActor
from app.interfaces.http.v1.staff_classwork.schemas import ToggleBody, ToggleResponse


async def toggle_journal_cell(
    body: ToggleBody, actor: TeacherActor, container: ContainerDep
) -> ToggleResponse:
    """Save at once; 409 if the lesson's attendance changed meanwhile."""
    version = await container.academic.classwork.toggle_journal_cell.execute(
        lesson_id=body.lesson_id,
        student_id=body.student_id,
        absent=body.absent,
        late=body.late,
        base_version=body.base_version,
        actor=actor,
    )
    return ToggleResponse(attendance_version=version)
