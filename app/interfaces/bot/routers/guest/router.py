"""Router of the guest mode; registered before Log in and before the linked catch-all.

Unlinked accounts: /start (choice or main menu), the choice buttons, /menu and free
text for guests. Everyone: the post tree buttons (audience by linked or not).
"""

from typing import Any

from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.guest import handlers
from app.interfaces.bot.routers.guest.callbacks import PostCb, StartModeCb
from app.modules.posts.domain.bot_mode import BotMode

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import TelegramObject, User


class IsGuest(Filter):
    """Passes for an unlinked account whose stored /start choice is guest."""

    async def __call__(
        self,
        event: TelegramObject,
        container: Any = None,
        event_from_user: User | None = None,
    ) -> bool:
        """Read the stored choice."""
        if container is None or event_from_user is None:
            return False
        mode = await container.posts.bot_modes.get(event_from_user.id)
        return bool(mode == BotMode.GUEST)


def build_router() -> Router:
    """Build the guest router."""
    router = Router(name="guest")
    unlinked = ~IsLinked()
    router.message.register(handlers.start, Command("start"), unlinked)
    router.callback_query.register(handlers.choose_mode, StartModeCb.filter(), unlinked)
    router.callback_query.register(handlers.open_post, PostCb.filter())
    router.message.register(handlers.show_menu, Command("menu"), unlinked, IsGuest())
    router.message.register(
        handlers.ask_assistant,
        F.text,
        ~F.text.startswith("/"),
        unlinked,
        IsGuest(),
    )
    return router
