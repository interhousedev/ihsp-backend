"""GET /v1/me/group/progress: the head student's view of their group."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_my_group_progress(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
) -> dict[str, Any]:
    """Return the group's marks and attendance; only for its head student."""
    use_case = container.academic.marks.get_group_progress
    data: dict[str, Any] = await use_case.for_head_student(actor, semester)
    return data
