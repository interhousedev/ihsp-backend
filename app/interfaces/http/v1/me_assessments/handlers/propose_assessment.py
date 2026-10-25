"""POST /v1/me/assessments (head student)."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_assessments.schemas import ProposalBody
from app.modules.academic.application.assessments.inputs import ProposalInput
from app.shared.actor import Actor, Role

from fastapi import Depends


async def propose_assessment(
    body: ProposalBody,
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    """Suggest a control date for the caller's group; it stays tentative."""
    item: dict[str, Any] = await container.academic.assessments.propose.execute(
        actor,
        ProposalInput(
            subject_id=body.subject_id,
            kind=body.kind,
            date=body.date,
            title=body.title,
            starts_at=body.starts_at,
            room=body.room,
            note=body.note,
            control=body.control,
        ),
    )
    return item
