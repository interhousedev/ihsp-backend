"""POST /v1/id/recovery/otp/confirm: schedule the OTP reset."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import (
    OtpRecoveryConfirmBody,
    OtpRecoveryConfirmResponse,
)


async def post_otp_confirm(
    body: OtpRecoveryConfirmBody, auth: AuthDep, ctx: CtxDep
) -> OtpRecoveryConfirmResponse:
    """Start the 24 hour countdown and warn the linked Telegram accounts."""
    effective_at = await auth.confirm_otp_reset.execute(body.login, body.code, ctx)
    return OtpRecoveryConfirmResponse(effective_at=effective_at)
