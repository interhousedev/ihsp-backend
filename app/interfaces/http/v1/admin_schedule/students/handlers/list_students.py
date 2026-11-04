"""GET /v1/admin/students."""

from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.students.schemas import (
    StudentItemResponse,
    StudentPageResponse,
)

from fastapi import Query


async def list_students(
    container: ContainerDep,
    actor: AdminActor,
    query: Annotated[str | None, Query(max_length=100)] = None,
    group_id: Annotated[UUID | None, Query()] = None,
    subgroup: Annotated[Literal[1, 2] | None, Query()] = None,
    status: Annotated[Literal["active", "left"] | None, Query()] = None,
    emis_status: Annotated[Literal["active", "needs_reauth"] | None, Query()] = None,
    registered: Annotated[bool | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> StudentPageResponse:
    """Search and filter students; names and photo links come from identity."""
    page = await container.academic.schedule.list_students.execute(
        query=query,
        group_id=group_id,
        subgroup=subgroup,
        status=status,
        emis_status=emis_status,
        registered=registered,
        cursor=cursor,
        limit=limit,
    )
    ids = [item.user_id for item in page.items]
    photos = await container.identity.directory.photo_urls(ids) if ids else {}
    return StudentPageResponse(
        items=[
            StudentItemResponse.from_data(item, photos.get(item.user_id))
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )
