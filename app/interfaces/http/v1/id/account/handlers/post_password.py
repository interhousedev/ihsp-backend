"""POST /v1/id/me/password: change the password."""

from app.interfaces.http.v1.id.account.schemas import ChangePasswordBody
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def post_password(
    body: ChangePasswordBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Verify the current password, apply the policy, log out other devices."""
    await auth.change_password.execute(
        actor, body.current_password, body.new_password, ctx
    )
    return Response(status_code=204)
