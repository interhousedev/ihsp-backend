"""PUT /v1/admin/groups/{id}/head-student."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import HeadStudentBody


async def set_head_student(
    group_id: UUID,
    body: HeadStudentBody,
    container: ContainerDep,
    actor: AdminActor,
) -> None:
    """Assign the head student (an active member of the group); null clears it."""
    await container.academic.schedule.set_head_student.execute(
        actor, group_id, body.student_id
    )
