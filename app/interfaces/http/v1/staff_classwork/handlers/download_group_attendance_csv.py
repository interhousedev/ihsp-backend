"""``GET /v1/staff/groups/{id}/attendance.csv``: the report as CSV (STF-13)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor

from fastapi import Query, Response


async def download_group_attendance_csv(
    id: UUID,
    actor: StaffActor,
    container: ContainerDep,
    view: Literal["student", "subject", "day", "lesson"] = "student",
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
) -> Response:
    """Return the current view as CSV."""
    data = await container.academic.classwork.group_attendance_csv.execute(
        actor, id, view, start, end
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="attendance.csv"'},
    )
