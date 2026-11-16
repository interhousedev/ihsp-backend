"""POST /v1/admin/users: create an invited account."""

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.users.schemas import (
    InvitedUserResponse,
    UserCreateBody,
)
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_user(
    body: UserCreateBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> InvitedUserResponse:
    """Store the account and return its one-time Telegram invitation link."""
    created = await auth.create_invited_user.execute(
        admin,
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        account_kind=body.account_kind,
        roles=body.roles,
        email=str(body.email) if body.email else None,
        phone=body.phone,
        ctx=ctx,
    )
    return InvitedUserResponse(
        user=AdminUserResponse.of(created.user), invite_url=created.invite_url
    )
