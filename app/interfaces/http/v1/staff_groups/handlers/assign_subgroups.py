"""PUT /v1/staff/groups/{id}/subgroups."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupDetailResponse,
    SubgroupsBody,
)
from app.interfaces.http.v1.staff_groups.deps import ContainerDep, CuratorActor


async def assign_subgroups(
    group_id: UUID,
    body: SubgroupsBody,
    container: ContainerDep,
    actor: CuratorActor,
) -> GroupDetailResponse:
    """Set students' subgroups; only the group's curator or an admin may."""
    detail = await container.academic.schedule.assign_subgroups.execute(
        actor, group_id, [(item.user_id, item.subgroup) for item in body.assignments]
    )
    return GroupDetailResponse.model_validate(detail)
