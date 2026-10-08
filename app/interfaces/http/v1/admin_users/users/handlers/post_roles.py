"""POST /v1/admin/users/{id}/roles."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.users.schemas import RolesBody
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_roles(
    id: UUID, body: RolesBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Grant and revoke roles; any change logs the user out everywhere."""
    user = await auth.change_roles.execute(
        admin, id, grant=body.grant, revoke=body.revoke, ctx=ctx
    )
    return AdminUserResponse.of(user)
