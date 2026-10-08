"""POST /v1/lms/courses/{id}/invite-code: rotate the invite code."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import InviteCodeResponse, respond


async def rotate_invite_code(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> InviteCodeResponse:
    """Replace the invite code; old invite links stop working."""
    view = await authoring.rotate_invite_code.execute(actor, course_id)
    return respond(InviteCodeResponse, view)
