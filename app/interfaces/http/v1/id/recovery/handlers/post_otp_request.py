"""POST /v1/id/recovery/otp/request: always 202."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import OtpRecoveryRequestBody

from fastapi import Response


async def post_otp_request(
    body: OtpRecoveryRequestBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Send the reset code to the recovery email if the account qualifies."""
    await auth.request_otp_reset.execute(body.login, ctx)
    return Response(status_code=202)
