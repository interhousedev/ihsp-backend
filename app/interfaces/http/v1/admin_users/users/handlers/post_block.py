"""POST /v1/admin/users/{id}/block."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import user_response
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.users.schemas import BlockBody
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_block(
    id: UUID, body: BlockBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Block the user and log them out everywhere."""
    user = await auth.block_user.execute(admin, id, body.reason, ctx)
    return await user_response(auth, user)
