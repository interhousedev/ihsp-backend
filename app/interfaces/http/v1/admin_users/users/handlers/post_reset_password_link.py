"""POST /v1/admin/users/{id}/reset-password-link: the reset link, not emailed."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.users.schemas import ActivationUrlResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_reset_password_link(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> ActivationUrlResponse:
    """Issue a reset link for the admin to hand over; nothing is emailed."""
    _, url = await auth.admin_reset_password.issue(
        admin, id, ctx, refuse_admin_target=True
    )
    return ActivationUrlResponse(activation_url=url)
