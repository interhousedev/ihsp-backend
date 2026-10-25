"""POST /v1/id/login/otp/request: send a login code (always 202)."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import OtpRequestBody, SentResponse


async def request_login_otp(
    body: OtpRequestBody, auth: AuthDep, ctx: CtxDep
) -> SentResponse:
    """Never reveals whether the account exists or has OTP enabled (ID-13)."""
    await auth.request_login_otp.execute(body.login, ctx)
    return SentResponse()
