"""POST /v1/admin/users/{id}/mail/suspend."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import user_response
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.users.schemas import SuspendBody
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_mail_suspend(
    id: UUID, body: SuspendBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Stop the mailbox from sending."""
    user = await auth.suspend_mail.execute(admin, id, body.reason, ctx)
    return await user_response(auth, user)
