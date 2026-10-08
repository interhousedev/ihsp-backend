"""POST /v1/admin/groups."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupCreateBody,
    GroupItemResponse,
)


async def create_group(
    body: GroupCreateBody, container: ContainerDep, actor: AdminActor
) -> GroupItemResponse:
    """Create a group in advance."""
    group = await container.academic.schedule.create_group.execute(
        name=body.name,
        emis_group_id=body.emis_group_id,
        current_semester=body.current_semester,
    )
    return GroupItemResponse.model_validate(group)
