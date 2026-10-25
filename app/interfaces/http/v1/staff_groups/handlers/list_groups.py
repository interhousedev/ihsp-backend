"""GET /v1/staff/groups."""

from app.interfaces.http.v1.admin_schedule.groups.schemas import GroupItemResponse
from app.interfaces.http.v1.staff_groups.deps import ContainerDep, TeacherActor


async def list_groups(
    container: ContainerDep, actor: TeacherActor
) -> list[GroupItemResponse]:
    """List the groups the caller curates."""
    groups = await container.academic.schedule.list_curated_groups.execute(actor)
    return [GroupItemResponse.model_validate(group) for group in groups]
