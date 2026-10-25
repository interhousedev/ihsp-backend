"""GET /v1/me/subjects/{subject_id}/lessons?around=now."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def list_subject_lessons(
    subject_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    around: Annotated[Literal["now"], Query()] = "now",
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
    past_limit: Annotated[int, Query(ge=1, le=100)] = 10,
    past_offset: Annotated[int, Query(ge=0)] = 0,
    upcoming_days: Annotated[int, Query(ge=0, le=60)] = 14,
) -> dict[str, Any]:
    """Return the latest past lessons, then the next `upcoming_days` of lessons."""
    result: dict[str, Any] = (
        await container.academic.marks.list_subject_lessons.execute(
            actor,
            subject_id,
            semester=semester,
            past_limit=past_limit,
            past_offset=past_offset,
            upcoming_days=upcoming_days,
        )
    )
    return result
