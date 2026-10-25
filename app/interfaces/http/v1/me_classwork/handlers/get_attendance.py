"""``GET /v1/me/attendance``: the student's own absences (WEB-17)."""

import datetime as dt
from typing import Annotated

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import StudentAttendanceResponse

from fastapi import Query


async def get_attendance(
    actor: StudentActor,
    container: ContainerDep,
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
) -> StudentAttendanceResponse:
    """Return absences per subject and per day; the default range is the term."""
    data = await container.academic.classwork.student_attendance.execute(
        actor, start, end
    )
    return StudentAttendanceResponse.model_validate(data)
