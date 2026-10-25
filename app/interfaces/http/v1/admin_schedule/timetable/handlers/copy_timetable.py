"""POST /v1/admin/timetable/copy."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    CopyBody,
    CopyResponse,
)


async def copy_timetable(
    body: CopyBody, container: ContainerDep, actor: AdminActor
) -> CopyResponse:
    """Copy the entries of one term into another."""
    created = await container.academic.schedule.copy_timetable.execute(
        body.from_term_id, body.to_term_id
    )
    return CopyResponse(created=created)
