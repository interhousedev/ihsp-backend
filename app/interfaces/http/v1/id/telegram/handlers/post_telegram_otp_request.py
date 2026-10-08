"""POST /v1/id/telegram/otp/request: a login code for the mini app page."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import SentResponse
from app.interfaces.http.v1.id.telegram.schemas import TelegramOtpRequestBody


async def post_telegram_otp_request(
    body: TelegramOtpRequestBody, auth: AuthDep, ctx: CtxDep
) -> SentResponse:
    """Always {sent: true}; /v1/id/telegram/login with otp_code completes it."""
    await auth.request_telegram_otp.execute(body.init_data, body.login, ctx)
    return SentResponse()
