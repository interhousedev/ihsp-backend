"""PATCH /v1/admin/timetable/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.timetable.inputs import to_entry_patch
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    TimetableEntryPatchBody,
    TimetableEntryResponse,
)


async def update_entry(
    entry_id: UUID,
    body: TimetableEntryPatchBody,
    container: ContainerDep,
    actor: AdminActor,
) -> TimetableEntryResponse:
    """Change an entry; 409 with params.conflicts when it clashes."""
    entry = await container.academic.schedule.update_entry.execute(
        actor, entry_id, to_entry_patch(body)
    )
    return TimetableEntryResponse.model_validate(entry)
