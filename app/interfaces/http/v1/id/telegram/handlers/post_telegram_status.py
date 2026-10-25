"""POST /v1/id/telegram/status: is this Telegram account linked?"""

from app.interfaces.http.v1.id.dependencies import AuthDep
from app.interfaces.http.v1.id.telegram.schemas import (
    TelegramStatusBody,
    TelegramStatusResponse,
)


async def post_telegram_status(
    body: TelegramStatusBody, auth: AuthDep
) -> TelegramStatusResponse:
    """Verify initData and report the link."""
    result = await auth.telegram_status.execute(body.init_data)
    return TelegramStatusResponse(linked=result.linked, login=result.login)
