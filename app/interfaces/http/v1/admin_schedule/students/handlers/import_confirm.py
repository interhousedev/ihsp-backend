"""POST /v1/admin/students/import/{import_id}/confirm."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.students.schemas import (
    ImportConfirmResponse,
)


async def import_confirm(
    import_id: UUID, container: ContainerDep, actor: AdminActor
) -> ImportConfirmResponse:
    """Create the groups and students of a previewed import."""
    result = await container.academic.schedule.import_confirm.execute(actor, import_id)
    return ImportConfirmResponse.model_validate(result)
