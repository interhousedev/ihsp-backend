"""POST /v1/admin/users/{id}/mail/resume."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import user_response
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_mail_resume(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Allow the mailbox to send again."""
    user = await auth.resume_mail.execute(admin, id, ctx)
    return await user_response(auth, user)
