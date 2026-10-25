"""GET /v1/admin/groups/{id}/curriculum."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.curriculum_schemas import (
    CurriculumResponse,
)


async def get_curriculum(
    group_id: UUID, container: ContainerDep, actor: AdminActor
) -> CurriculumResponse | None:
    """Return the group's EMIS curriculum, or null when none is stored yet."""
    view = await container.academic.schedule.get_group_curriculum.execute(group_id)
    return CurriculumResponse.model_validate(view) if view else None
