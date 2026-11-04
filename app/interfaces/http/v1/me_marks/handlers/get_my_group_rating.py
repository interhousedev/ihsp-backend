"""GET /v1/me/group/rating: the head student's group ranked by semester GPA."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_marks.schemas import GroupRatingRow
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_my_group_rating(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
) -> list[GroupRatingRow]:
    """The group's students by GPA; only for its head student (as group progress)."""
    rows: list[dict[str, Any]] = (
        await container.academic.marks.get_group_rating.for_head_student(
            actor, semester
        )
    )
    return [GroupRatingRow(**row) for row in rows]
