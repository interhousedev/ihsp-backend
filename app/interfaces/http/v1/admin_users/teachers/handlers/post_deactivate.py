"""POST /v1/admin/teachers/{id}/deactivate."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import user_response
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_deactivate(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Revoke access and flag the teacher's future lessons."""
    user = await auth.deactivate_teacher.execute(admin, id, ctx)
    return await user_response(auth, user)
