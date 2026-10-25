"""POST /v1/admin/users/{id}/reset-password."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.users.schemas import ActivationUrlResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_reset_password(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> ActivationUrlResponse:
    """Issue a reset link (also emailed to the user)."""
    url = await auth.admin_reset_password.execute(admin, id, ctx)
    return ActivationUrlResponse(activation_url=url)
