"""GET /v1/staff/groups/{id}/progress."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.http.v1.staff_groups.deps import ContainerDep, CuratorActor

from fastapi import Query


async def get_group_progress(
    group_id: UUID,
    container: ContainerDep,
    actor: CuratorActor,
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
) -> dict[str, Any]:
    """Return marks and attendance per student; only its curator or an admin."""
    use_case = container.academic.marks.get_group_progress
    data: dict[str, Any] = await use_case.for_staff(actor, group_id, semester)
    return data
