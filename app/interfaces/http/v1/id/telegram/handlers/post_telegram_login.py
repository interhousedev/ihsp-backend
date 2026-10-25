"""POST /v1/id/telegram/login: log in on the mini app page and link Telegram."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import LoginResultResponse
from app.interfaces.http.v1.id.telegram.schemas import (
    TelegramLinkedResponse,
    TelegramLoginBody,
)


async def post_telegram_login(
    body: TelegramLoginBody, auth: AuthDep, ctx: CtxDep
) -> TelegramLinkedResponse | LoginResultResponse:
    """Link the account, or ask Administration for the second factor."""
    result = await auth.telegram_login.execute(
        body.init_data,
        body.login,
        password=body.password,
        otp_code=body.otp_code,
        ctx=ctx,
    )
    if result.second_factor_result is not None:
        return LoginResultResponse.of(result.second_factor_result)
    return TelegramLinkedResponse(login=result.login)
