"""DELETE /v1/admin/assessments/{id}."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Response


async def delete_assessment(
    assessment_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Cancel a control; the row stays, so a dismissed EMIS suggestion stays so."""
    await container.academic.assessments.delete.execute(actor, assessment_id)
    return Response(status_code=204)
