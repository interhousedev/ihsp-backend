"""POST /v1/id/login: password login."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import LoginBody, LoginResultResponse


async def post_login(
    body: LoginBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """Check the password; Administration gets a second factor ticket."""
    result = await auth.log_in_with_password.execute(
        body.login_challenge,
        body.login,
        body.password,
        remember=body.remember,
        ctx=ctx,
    )
    return LoginResultResponse.of(result)
