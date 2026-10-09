"""PATCH /v1/admin/assessments/{id}."""

from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_assessments.schemas import AssessmentPatchBody
from app.interfaces.http.v1.staff_assessments.mapping import to_patch
from app.shared.actor import Actor, Role

from fastapi import Depends


async def update_assessment(
    assessment_id: UUID,
    body: AssessmentPatchBody,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    """Edit, confirm (`status: planned`) or dismiss (`status: cancelled`) a control."""
    item: dict[str, Any] = await container.academic.assessments.update.execute(
        actor, assessment_id, to_patch(body)
    )
    return item
