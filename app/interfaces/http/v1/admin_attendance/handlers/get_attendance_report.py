"""``GET /v1/admin/attendance``: Administration's attendance report (ADM-12)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admin_attendance.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.staff_classwork.schemas import AttendanceReportResponse

from fastapi import Query


async def get_attendance_report(
    actor: AdminActor,
    container: ContainerDep,
    view: Literal["group", "student", "subject", "teacher"] = "group",
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
    group_id: UUID | None = None,
) -> AttendanceReportResponse:
    """Return absences per group, student, subject or teacher."""
    data = await container.academic.classwork.attendance_report.execute(
        actor, view, start, end, group_id
    )
    return AttendanceReportResponse.model_validate(data)
