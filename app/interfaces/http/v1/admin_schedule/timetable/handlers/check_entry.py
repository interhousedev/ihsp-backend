"""POST /v1/admin/timetable/check."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.timetable.inputs import to_entry_input
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    CheckResponse,
    ConflictResponse,
    TimetableEntryInputBody,
)

from fastapi import Query


async def check_entry(
    body: TimetableEntryInputBody,
    container: ContainerDep,
    actor: AdminActor,
    entry_id: Annotated[UUID | None, Query()] = None,
) -> CheckResponse:
    """Return the conflicts the entry would have, without saving it.

    Pass entry_id to skip the entry that is being edited.
    """
    conflicts = await container.academic.schedule.check_entry.execute(
        to_entry_input(body), entry_id=entry_id
    )
    return CheckResponse(
        conflicts=[ConflictResponse.model_validate(item) for item in conflicts]
    )
