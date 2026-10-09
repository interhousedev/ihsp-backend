"""GET /v1/me/subjects/{subject_id}/planner."""

from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.modules.academic.domain.marks.planner import MAX_WHAT_IF, parse_what_if
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_planner(
    subject_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
    what_if: Annotated[
        list[str] | None,
        Query(
            max_length=MAX_WHAT_IF,
            description="Hypothetical marks, `<lesson|midterm|final>:<2..5>`.",
        ),
    ] = None,
) -> dict[str, Any]:
    """Return the predicted semester mark and what the controls must bring."""
    marks = [parse_what_if(raw) for raw in what_if or []]
    plan: dict[str, Any] = await container.academic.marks.get_subject_planner.execute(
        actor, subject_id, semester, marks
    )
    return plan
