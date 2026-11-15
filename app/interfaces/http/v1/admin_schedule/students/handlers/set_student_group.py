"""PUT /v1/admin/students/{user_id}/group."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.students.schemas import StudentGroupBody

from fastapi import Response


async def set_student_group(
    user_id: UUID,
    body: StudentGroupBody,
    container: ContainerDep,
    actor: AdminActor,
) -> Response:
    """Set or change the student's group; null detaches the student."""
    await container.academic.schedule.set_student_group.execute(
        actor, user_id, body.group_id
    )
    return Response(status_code=204)
