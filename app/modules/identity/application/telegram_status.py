"""POST /v1/id/telegram/status: is the Telegram account of this initData linked?"""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.ports.init_data_verifier import InitDataVerifier
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class TelegramStatusResult:
    """Linked flag and the login of the linked account."""

    linked: bool
    login: str | None


@dataclass(frozen=True, slots=True)
class TelegramStatus:
    """Lets the mini app login page skip the form for linked accounts."""

    uow_factory: UowFactory
    verifier: InitDataVerifier
    max_age: timedelta

    async def execute(self, init_data: str) -> TelegramStatusResult:
        """Verify initData and look the account up."""
        telegram_user = self.verifier.verify(init_data, max_age=self.max_age)
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user.id)
            user = await uow.users.get(link.user_id) if link else None
        if user is None or not user.is_active:
            return TelegramStatusResult(linked=False, login=None)
        return TelegramStatusResult(linked=True, login=user.login)
