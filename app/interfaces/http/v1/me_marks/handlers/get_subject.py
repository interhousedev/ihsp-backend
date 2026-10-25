"""GET /v1/me/subjects/{subject_id}."""

from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_subject(
    subject_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
) -> dict[str, Any]:
    """Return one subject with its lessons, marks and materials."""
    detail: dict[str, Any] = await container.academic.marks.get_subject_detail.execute(
        actor, subject_id, semester
    )
    return detail
