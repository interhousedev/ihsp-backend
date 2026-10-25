"""PATCH /v1/admin/users/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import user_response
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.users.schemas import UserPatchBody
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def patch_user(
    id: UUID, body: UserPatchBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Edit the names, the login and the email of any user."""
    user = await auth.update_user.execute(
        admin,
        id,
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        login=body.login,
        email=str(body.email) if body.email else None,
        ctx=ctx,
    )
    return await user_response(auth, user)
