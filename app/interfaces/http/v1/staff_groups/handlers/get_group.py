"""GET /v1/staff/groups/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.groups.schemas import GroupDetailResponse
from app.interfaces.http.v1.staff_groups.deps import ContainerDep, CuratorActor


async def get_group(
    group_id: UUID, container: ContainerDep, actor: CuratorActor
) -> GroupDetailResponse:
    """Return a group; only its curator or an admin may see it."""
    detail = await container.academic.schedule.get_group_detail.execute(actor, group_id)
    return GroupDetailResponse.model_validate(detail)
