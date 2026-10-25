"""GET /v1/me/subjects."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def list_subjects(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
) -> list[dict[str, Any]]:
    """Return the subjects of a semester with marks, absences and next lesson."""
    cards: list[dict[str, Any]] = await container.academic.marks.list_subjects.execute(
        actor, semester
    )
    return cards
