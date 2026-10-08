"""POST /v1/admin/timetable."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.timetable.inputs import to_entry_input
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    TimetableEntryInputBody,
    TimetableEntryResponse,
)


async def create_entry(
    body: TimetableEntryInputBody, container: ContainerDep, actor: AdminActor
) -> TimetableEntryResponse:
    """Create an entry; 409 with params.conflicts when it clashes."""
    entry = await container.academic.schedule.create_entry.execute(
        actor, to_entry_input(body)
    )
    return TimetableEntryResponse.model_validate(entry)
