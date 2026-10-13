"""GET /v1/me/timetable."""

import datetime as dt
from typing import Annotated

from app.interfaces.http.v1.me_schedule.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_schedule.schemas import StudentLessonItemResponse

from fastapi import Query


async def get_timetable(
    container: ContainerDep,
    actor: StudentActor,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: Annotated[dt.date | None, Query()] = None,
) -> list[StudentLessonItemResponse]:
    """Return the student's lessons between two dates (default: this week)."""
    items = await container.academic.schedule.get_student_timetable.execute(
        actor, from_, to
    )
    return [StudentLessonItemResponse.model_validate(item) for item in items]
