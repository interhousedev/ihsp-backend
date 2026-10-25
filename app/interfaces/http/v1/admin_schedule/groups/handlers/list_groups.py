"""GET /v1/admin/groups."""

from typing import Annotated, Literal

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import GroupItemResponse

from fastapi import Query


async def list_groups(
    container: ContainerDep,
    actor: AdminActor,
    status: Annotated[Literal["active", "archived"] | None, Query()] = None,
) -> list[GroupItemResponse]:
    """List groups with student and subgroup counts."""
    groups = await container.academic.schedule.list_groups.execute(status)
    return [GroupItemResponse.model_validate(group) for group in groups]
