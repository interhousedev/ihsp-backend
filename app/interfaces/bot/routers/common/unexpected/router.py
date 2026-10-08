"""Last router: whatever nobody else handled."""

from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.common.unexpected.handlers.show_hint import show_hint
from app.interfaces.bot.routers.common.unexpected.handlers.stale_button import (
    stale_button,
)

from aiogram import Router


def register_filters(router: Router) -> None:
    """Hints are for linked accounts (others got the login screen already)."""
    router.message.filter(IsLinked())


def build_router() -> Router:
    """Build the fallback router."""
    router = Router(name="common.unexpected")
    register_filters(router)
    router.message.register(show_hint)
    router.callback_query.register(stale_button)
    return router
