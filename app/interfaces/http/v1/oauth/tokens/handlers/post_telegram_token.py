"""POST /v1/oauth/telegram: mini app login with signed initData."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.oauth.tokens.schemas import (
    TelegramTokenBody,
    TokenResponse,
)


async def post_telegram_token(
    body: TelegramTokenBody, auth: AuthDep, ctx: CtxDep
) -> TokenResponse:
    """Access token only, never a cookie (cookies are unreliable in Telegram)."""
    grant = await auth.exchange_telegram_init_data.execute(
        body.client_id, body.init_data, ctx
    )
    return TokenResponse.of(grant)
