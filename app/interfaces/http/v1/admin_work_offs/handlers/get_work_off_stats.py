"""``GET /v1/admin/work-offs/stats``: work-off counts by key (WO-8)."""

import datetime as dt
from typing import Annotated, Literal

from app.interfaces.http.v1.admin_work_offs.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_work_offs.schemas import WorkOffStatsResponse

from fastapi import Query


async def get_work_off_stats(
    actor: AdminActor,
    container: ContainerDep,
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
    group_by: Literal["subject", "teacher", "group", "student"] = "subject",
) -> WorkOffStatsResponse:
    """Return open and done counts per subject, teacher, group or student."""
    data = await container.academic.classwork.work_off_stats.execute(
        actor, group_by=group_by, start=start, end=end
    )
    return WorkOffStatsResponse.model_validate(data)
