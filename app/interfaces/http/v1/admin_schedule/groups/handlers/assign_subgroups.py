"""PUT /v1/admin/groups/{id}/subgroups."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupDetailResponse,
    SubgroupsBody,
)


async def assign_subgroups(
    group_id: UUID,
    body: SubgroupsBody,
    container: ContainerDep,
    actor: AdminActor,
) -> GroupDetailResponse:
    """Set the subgroup of several students at once."""
    detail = await container.academic.schedule.assign_subgroups.execute(
        actor, group_id, [(item.user_id, item.subgroup) for item in body.assignments]
    )
    return GroupDetailResponse.model_validate(detail)
