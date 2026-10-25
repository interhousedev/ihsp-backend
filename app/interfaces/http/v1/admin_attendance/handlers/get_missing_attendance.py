"""``GET /v1/admin/attendance/missing``: teachers with lessons not submitted."""

import datetime as dt
from typing import Annotated

from app.interfaces.http.v1.admin_attendance.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_attendance.schemas import MissingAttendanceResponse

from fastapi import Query


async def get_missing_attendance(
    actor: AdminActor,
    container: ContainerDep,
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
) -> list[MissingAttendanceResponse]:
    """Return finished lessons without attendance, grouped by teacher."""
    data = await container.academic.classwork.missing_attendance.execute(
        actor, start, end
    )
    return [MissingAttendanceResponse.model_validate(row) for row in data]
