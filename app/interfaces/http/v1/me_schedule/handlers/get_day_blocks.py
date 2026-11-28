"""GET /v1/me/timetable/day-blocks."""

import datetime as dt
from typing import Annotated

from app.interfaces.http.v1.admin_schedule.day_blocks.schemas import (
    DayBlockOccurrenceResponse,
)
from app.interfaces.http.v1.me_schedule.deps import ContainerDep, StudentActor

from fastapi import Query


async def get_day_blocks(
    container: ContainerDep,
    actor: StudentActor,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: Annotated[dt.date | None, Query()] = None,
) -> list[DayBlockOccurrenceResponse]:
    """Lunch, breaks and other non-lesson blocks of the student's group per date."""
    items = await container.academic.day_blocks.student_blocks.execute(
        actor.user_id, from_, to
    )
    return [DayBlockOccurrenceResponse.model_validate(item) for item in items]
