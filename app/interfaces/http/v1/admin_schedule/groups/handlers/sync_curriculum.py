"""POST /v1/admin/groups/{id}/curriculum/sync."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.curriculum_schemas import (
    CurriculumResponse,
    CurriculumSyncResponse,
)


async def sync_curriculum(
    group_id: UUID, container: ContainerDep, actor: AdminActor
) -> CurriculumSyncResponse:
    """Read the curriculum from EMIS now and return what is stored for the group."""
    result = await container.academic.emis_import.sync_group_curriculum.execute(
        group_id
    )
    view = await container.academic.schedule.get_group_curriculum.execute(group_id)
    return CurriculumSyncResponse(
        status=result.status,
        curriculum=CurriculumResponse.model_validate(view) if view else None,
    )
