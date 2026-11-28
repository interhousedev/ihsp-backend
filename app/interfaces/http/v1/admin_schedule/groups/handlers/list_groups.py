"""GET /v1/admin/groups."""

from typing import Annotated, Literal

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import GroupItemResponse

from fastapi import Query


async def list_groups(
    container: ContainerDep,
    actor: AdminActor,
    status: Annotated[Literal["active", "archived"] | None, Query()] = None,
    include_hidden: Annotated[bool, Query()] = False,
) -> list[GroupItemResponse]:
    """List groups with student and subgroup counts; hidden ones on request."""
    groups = await container.academic.schedule.list_groups.execute(
        status, include_hidden=include_hidden
    )
    return [GroupItemResponse.model_validate(group) for group in groups]
