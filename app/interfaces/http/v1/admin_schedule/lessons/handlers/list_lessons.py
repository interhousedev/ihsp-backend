"""GET /v1/admin/lessons."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.lessons.schemas import LessonPageResponse
from app.modules.academic.application.schedule.ports.reader import LessonFilters

from fastapi import Query


async def list_lessons(
    container: ContainerDep,
    actor: AdminActor,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: Annotated[dt.date | None, Query()] = None,
    group_id: Annotated[UUID | None, Query()] = None,
    teacher_id: Annotated[UUID | None, Query()] = None,
    room_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[Literal["scheduled", "cancelled"] | None, Query()] = None,
    teacher_needed: Annotated[bool | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LessonPageResponse:
    """Search lessons; the cursor pages by date, period and id."""
    filters = LessonFilters(
        start=from_,
        end=to,
        group_id=group_id,
        teacher_id=teacher_id,
        room_id=room_id,
        status=status,
        teacher_needed=teacher_needed,
    )
    page = await container.academic.schedule.list_lessons.execute(
        actor, filters, cursor=cursor, limit=limit
    )
    return LessonPageResponse.model_validate(page, from_attributes=True)
