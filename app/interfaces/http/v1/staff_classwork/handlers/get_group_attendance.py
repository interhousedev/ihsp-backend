"""``GET /v1/staff/groups/{id}/attendance``: the curator's report (STF-13)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import AttendanceReportResponse

from fastapi import Query


async def get_group_attendance(
    id: UUID,
    actor: StaffActor,
    container: ContainerDep,
    view: Literal["student", "subject", "day", "lesson"] = "student",
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
) -> AttendanceReportResponse:
    """Return absences per student, subject, day or lesson."""
    data = await container.academic.classwork.group_attendance.execute(
        actor, id, view, start, end
    )
    return AttendanceReportResponse.model_validate(data)
