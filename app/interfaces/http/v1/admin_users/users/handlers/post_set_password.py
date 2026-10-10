"""POST /v1/admin/users/{id}/set-password."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.users.schemas import SetPasswordBody
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_set_password(
    id: UUID, body: SetPasswordBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> None:
    """Set the password (initial password of a teacher); sessions end."""
    await auth.admin_set_password.execute(
        admin, id, body.password, require_change=body.require_change, ctx=ctx
    )
