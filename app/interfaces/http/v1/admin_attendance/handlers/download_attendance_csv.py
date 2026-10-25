"""``GET /v1/admin/attendance.csv``: the report as a spreadsheet (ADM-12)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admin_attendance.deps import AdminActor, ContainerDep

from fastapi import Query, Response


async def download_attendance_csv(
    actor: AdminActor,
    container: ContainerDep,
    view: Literal["group", "student", "subject", "teacher"] = "group",
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
    group_id: UUID | None = None,
) -> Response:
    """Return the current view as CSV."""
    data = await container.academic.classwork.attendance_report_csv.execute(
        actor, view, start, end, group_id
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="attendance.csv"'},
    )
