"""Filter: the linked user holds one of the given roles."""

from app.shared.actor import Actor, Role

from aiogram.filters import Filter
from aiogram.types import TelegramObject


class HasRole(Filter):
    """Passes when the actor holds at least one of the roles."""

    def __init__(self, *roles: Role) -> None:
        """Store the accepted roles."""
        self.roles = frozenset(roles)

    async def __call__(self, event: TelegramObject, actor: Actor | None = None) -> bool:
        """Return True when the actor holds one of the roles."""
        return actor is not None and bool(actor.roles & self.roles)
