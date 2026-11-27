"""GET /v1/me/group/rankings: groups of the course or lyceum by GPA or attendance."""

from typing import Annotated, Any, Literal

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_marks.schemas import GroupRankingsResponse
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_my_group_rankings(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    scope: Annotated[Literal["course", "lyceum"], Query()] = "course",
    metric: Annotated[Literal["gpa", "attendance"], Query()] = "gpa",
) -> GroupRankingsResponse:
    """Aggregates of every ranked group; members of other groups are never shown."""
    items: list[dict[str, Any]] = (
        await container.academic.marks.get_group_rankings.execute(actor, scope, metric)
    )
    return GroupRankingsResponse.model_validate({"items": items})
