"""POST /v1/admin/users/{id}/unblock."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_unblock(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Restore the account."""
    user = await auth.unblock_user.execute(admin, id, ctx)
    return AdminUserResponse.of(user)
