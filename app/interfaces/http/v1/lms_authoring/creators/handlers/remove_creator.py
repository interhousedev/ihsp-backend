"""DELETE /v1/staff/lms/creators/{user_id}: take the creator role away."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep


async def remove_creator(
    user_id: UUID, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> None:
    """Revoke `lms_creator` (LMS admins only); the person's courses stay theirs."""
    await auth.manage_course_creators.remove(actor, user_id, ctx)
