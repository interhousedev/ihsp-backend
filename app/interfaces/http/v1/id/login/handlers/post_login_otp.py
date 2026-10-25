"""POST /v1/id/login/otp: finish a login with a code."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import LoginResultResponse, OtpLoginBody


async def post_login_otp(
    body: OtpLoginBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """Second factor (with a ticket) or passwordless login (without)."""
    result = await auth.log_in_with_otp.execute(
        body.login_challenge,
        body.login,
        body.code,
        ticket=body.ticket,
        ctx=ctx,
    )
    return LoginResultResponse.of(result)
