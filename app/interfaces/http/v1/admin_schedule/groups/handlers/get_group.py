"""GET /v1/admin/groups/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import GroupDetailResponse


async def get_group(
    group_id: UUID, container: ContainerDep, actor: AdminActor
) -> GroupDetailResponse:
    """Return a group with its students."""
    detail = await container.academic.schedule.get_group_detail.execute(actor, group_id)
    return GroupDetailResponse.model_validate(detail)
