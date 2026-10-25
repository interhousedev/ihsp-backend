"""POST /v1/id/login/password: replace an administrator-set password at login."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import (
    LoginResultResponse,
    NewPasswordLoginBody,
)


async def post_login_password(
    body: NewPasswordLoginBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """Set the new password, then finish the login."""
    result = await auth.log_in_with_new_password.execute(
        body.login_challenge, body.ticket, body.new_password, ctx=ctx
    )
    return LoginResultResponse.of(result)
