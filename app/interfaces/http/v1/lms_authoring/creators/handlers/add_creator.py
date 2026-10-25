"""PUT /v1/staff/lms/creators/{user_id}: let a teacher or an admin create courses."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep
from app.interfaces.http.v1.lms_authoring.creators.schemas import (
    CourseCreatorResponse,
)


async def add_creator(
    user_id: UUID, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> CourseCreatorResponse:
    """Grant `lms_creator` (LMS admins only); students are refused."""
    user = await auth.manage_course_creators.add(actor, user_id, ctx)
    return CourseCreatorResponse.of(user)
