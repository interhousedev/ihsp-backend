"""POST /v1/lms/courses/{id}/steps: create a step."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CreateStepBody,
    StepDraftResponse,
    respond,
)


async def create_step(
    course_id: UUID, body: CreateStepBody, actor: ActorDep, authoring: AuthoringDep
) -> StepDraftResponse:
    """Create an empty step in a section of the draft outline."""
    view = await authoring.create_step.execute(
        actor,
        course_id,
        section_id=body.section_id,
        title=body.title,
        position=body.position,
    )
    return respond(StepDraftResponse, view)
