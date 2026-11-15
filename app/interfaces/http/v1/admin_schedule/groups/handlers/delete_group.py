"""DELETE /v1/admin/groups/{id}."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep

from fastapi import Query, Response


async def delete_group(
    group_id: UUID,
    container: ContainerDep,
    actor: AdminActor,
    move_students_to: Annotated[UUID | None, Query()] = None,
) -> Response:
    """Delete a group; its students move to the target group or lose their group."""
    await container.academic.schedule.delete_group.execute(
        actor, group_id, move_students_to
    )
    return Response(status_code=204)
