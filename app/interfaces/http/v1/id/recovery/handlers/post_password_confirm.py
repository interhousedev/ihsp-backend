"""POST /v1/id/recovery/password/confirm: set a new password."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import PasswordConfirmBody

from fastapi import Response


async def post_password_confirm(
    body: PasswordConfirmBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Check the code and the policy, change the password, log out everywhere."""
    await auth.confirm_password_reset.execute(
        body.login_or_email, body.code, body.new_password, ctx
    )
    return Response(status_code=204)
