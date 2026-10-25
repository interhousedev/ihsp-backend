"""POST /v1/id/recovery/otp/cancel: the Cancel button in Telegram."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import OtpRecoveryCancelBody

from fastapi import Response


async def post_otp_cancel(
    body: OtpRecoveryCancelBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Stop a pending reset (204 even for an unknown request)."""
    await auth.cancel_otp_reset.execute(body.request_id, ctx)
    return Response(status_code=204)
