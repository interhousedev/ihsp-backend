"""GET /v1/id/me/telegram: linked Telegram accounts."""

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep
from app.interfaces.http.v1.id.schemas import TelegramAccountResponse


async def get_telegram(actor: ActorDep, auth: AuthDep) -> list[TelegramAccountResponse]:
    """List the links."""
    links = await auth.list_telegram_accounts.execute(actor)
    return [TelegramAccountResponse.of(link) for link in links]
