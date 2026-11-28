"""PUT /v1/admin/groups/{id}/hidden."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupDetailResponse,
    GroupHiddenBody,
)


async def set_group_hidden(
    group_id: UUID,
    body: GroupHiddenBody,
    container: ContainerDep,
    actor: AdminActor,
) -> GroupDetailResponse:
    """Hide a group from lists, pickers and standings, or show it again."""
    detail = await container.academic.schedule.update_group.execute(
        actor, group_id, hidden=body.hidden
    )
    return GroupDetailResponse.model_validate(detail)
