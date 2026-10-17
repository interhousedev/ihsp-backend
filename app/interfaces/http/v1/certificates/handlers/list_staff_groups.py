"""GET /v1/certificates/staff/groups."""

from app.interfaces.http.v1.certificates.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.certificates.schemas import StaffGroupResponse


async def list_staff_groups(
    container: ContainerDep, actor: StaffActor
) -> list[StaffGroupResponse]:
    """Return the groups the caller may filter by."""
    groups = await container.certificates.list_staff_groups.execute(actor)
    return [StaffGroupResponse.from_info(g) for g in groups]
