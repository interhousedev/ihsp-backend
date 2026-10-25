"""POST /v1/id/login: password login, with a login or an EMIS ID."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import LoginBody, LoginResultResponse


async def post_login(
    body: LoginBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """Check the password; Administration gets a second factor ticket."""
    if body.emis_id is not None:
        result = await auth.log_in_with_emis_id.execute(
            body.login_challenge,
            body.emis_id,
            body.password,
            remember=body.remember,
            ctx=ctx,
        )
        return LoginResultResponse.of(result)
    result = await auth.log_in_with_password.execute(
        body.login_challenge,
        body.login or "",
        body.password,
        remember=body.remember,
        ctx=ctx,
    )
    return LoginResultResponse.of(result)
