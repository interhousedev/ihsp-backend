"""GET /v1/admin/timetable."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.timetable.schemas import (
    TimetableEntryResponse,
)

from fastapi import Query


async def list_entries(
    container: ContainerDep,
    actor: AdminActor,
    term_id: Annotated[UUID | None, Query()] = None,
    group_id: Annotated[UUID | None, Query()] = None,
    teacher_id: Annotated[UUID | None, Query()] = None,
    room_id: Annotated[UUID | None, Query()] = None,
) -> list[TimetableEntryResponse]:
    """List a term's entries (default: current), by group, teacher or room."""
    entries = await container.academic.schedule.list_entries.execute(
        actor,
        term_id=term_id,
        group_id=group_id,
        teacher_id=teacher_id,
        room_id=room_id,
    )
    return [TimetableEntryResponse.model_validate(entry) for entry in entries]
