"""DELETE /v1/admin/groups/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep

from fastapi import Response


async def delete_group(
    group_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Delete a group; its students stay as users without a group."""
    await container.academic.schedule.delete_group.execute(actor, group_id)
    return Response(status_code=204)
