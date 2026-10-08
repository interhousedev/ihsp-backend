"""GET /v1/lms/courses/{id}/preview/steps/{step_id}: student render of a draft."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import PreviewStepResponse, respond


async def preview_step(
    course_id: UUID, step_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> PreviewStepResponse:
    """Render the draft of a step without correct answers (needs `view_drafts`)."""
    view = await authoring.preview_step.execute(actor, course_id, step_id)
    return respond(PreviewStepResponse, view)
