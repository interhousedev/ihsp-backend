"""``GET /v1/admin/work-offs``: filtered, paged work-offs (WO-8)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admin_work_offs.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_work_offs.schemas import AdminWorkOffListResponse

from fastapi import Query


async def list_admin_work_offs(
    actor: AdminActor,
    container: ContainerDep,
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
    subject_id: UUID | None = None,
    teacher_id: UUID | None = None,
    group_id: UUID | None = None,
    student_id: UUID | None = None,
    status: Literal["open", "done", "all"] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminWorkOffListResponse:
    """Return one page of work-offs matching the filters."""
    data = await container.academic.classwork.list_admin_work_offs.execute(
        actor,
        start=start,
        end=end,
        subject_id=subject_id,
        teacher_id=teacher_id,
        group_id=group_id,
        student_id=student_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return AdminWorkOffListResponse.model_validate(data)
