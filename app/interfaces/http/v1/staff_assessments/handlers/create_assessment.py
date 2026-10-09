"""POST /v1/staff/assessments."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_assessments.schemas import AssessmentCreateBody
from app.interfaces.http.v1.staff_assessments.mapping import to_input
from app.shared.actor import Actor, Role

from fastapi import Depends


async def create_assessment(
    body: AssessmentCreateBody,
    actor: Annotated[Actor, Depends(require_roles(Role.TEACHER, Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    """Plan a control; a teacher must teach the subject in every group."""
    item: dict[str, Any] = await container.academic.assessments.create.execute(
        actor, to_input(body)
    )
    return item
