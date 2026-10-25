"""GET /v1/staff/timetable."""

import datetime as dt
from typing import Annotated

from app.interfaces.http.v1.admin_schedule.shared_schemas import LessonItemResponse
from app.interfaces.http.v1.me_schedule.deps import ContainerDep, TeacherActor

from fastapi import Query


async def get_staff_timetable(
    container: ContainerDep,
    actor: TeacherActor,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: Annotated[dt.date | None, Query()] = None,
) -> list[LessonItemResponse]:
    """Return the lessons the teacher teaches between two dates."""
    items = await container.academic.schedule.get_staff_timetable.execute(
        actor, from_, to
    )
    return [LessonItemResponse.model_validate(item) for item in items]
