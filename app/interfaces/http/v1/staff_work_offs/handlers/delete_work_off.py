"""``DELETE /v1/staff/work-offs/{id}``: remove a work-off (WO-3)."""

from uuid import UUID

from app.interfaces.http.v1.staff_work_offs.deps import ContainerDep, StaffActor

from fastapi import Response


async def delete_work_off(
    id: UUID, actor: StaffActor, container: ContainerDep
) -> Response:
    """Delete one work-off of a lesson the actor teaches."""
    await container.academic.classwork.delete_work_off.execute(id, actor)
    return Response(status_code=204)
