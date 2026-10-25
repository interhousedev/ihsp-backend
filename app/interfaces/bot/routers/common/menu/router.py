"""Router of the main menu and /help (linked users only)."""

from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.common.menu.handlers.show_help import show_help
from app.interfaces.bot.routers.common.menu.handlers.show_menu import show_menu
from app.shared.contracts.callbacks import MenuCb

from aiogram import F, Router
from aiogram.filters import Command


def register_filters(router: Router) -> None:
    """Menu screens are for linked accounts."""
    router.message.filter(IsLinked())
    router.callback_query.filter(IsLinked())


def build_router() -> Router:
    """Build the menu router."""
    router = Router(name="common.menu")
    register_filters(router)
    router.message.register(show_menu, Command("start", "menu"))
    router.callback_query.register(show_menu, MenuCb.filter(F.screen == "menu"))
    router.message.register(show_help, Command("help"))
    return router
