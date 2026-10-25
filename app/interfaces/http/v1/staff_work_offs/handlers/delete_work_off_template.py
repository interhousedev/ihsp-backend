"""``DELETE /v1/staff/work-off-templates/{id}``: remove a template (WO-1)."""

from uuid import UUID

from app.interfaces.http.v1.staff_work_offs.deps import ContainerDep, StaffActor

from fastapi import Response


async def delete_work_off_template(
    id: UUID, actor: StaffActor, container: ContainerDep
) -> Response:
    """Delete one of the actor's templates."""
    await container.academic.classwork.delete_work_off_template.execute(actor, id)
    return Response(status_code=204)
