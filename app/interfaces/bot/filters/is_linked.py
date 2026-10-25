"""Filter: the Telegram account is linked to an active IHSP account."""

from app.shared.contracts.identity import UserRef

from aiogram.filters import Filter
from aiogram.types import TelegramObject


class IsLinked(Filter):
    """Passes when the actor middleware found a linked user."""

    async def __call__(
        self, event: TelegramObject, user: UserRef | None = None
    ) -> bool:
        """Return True for linked accounts."""
        return user is not None
