"""GET /v1/id/me/telegram: linked Telegram accounts."""

from dataclasses import dataclass

from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class ListTelegramAccounts:
    """Lists the caller's Telegram links."""

    uow_factory: UowFactory

    async def execute(self, actor: Actor) -> list[TelegramLink]:
        """Oldest link first."""
        async with self.uow_factory() as uow:
            return await uow.telegram_links.list_for_user(actor.user_id)
