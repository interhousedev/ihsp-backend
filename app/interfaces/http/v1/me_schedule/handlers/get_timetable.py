"""GET /v1/me/timetable."""

import datetime as dt
from typing import Annotated

from app.interfaces.http.v1.me_classwork.schemas import ExcuseRefResponse
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
    rows = [StudentLessonItemResponse.model_validate(item) for item in items]
    if not rows:
        return []
    excuses = await container.academic.classwork.student_excuses.execute(
        actor.user_id, min(r.date for r in rows), max(r.date for r in rows)
    )
    for row in rows:
        ref = excuses.get(row.id)
        row.excused = ref is not None
        row.excuse = None if ref is None else ExcuseRefResponse.model_validate(ref)
    return rows
