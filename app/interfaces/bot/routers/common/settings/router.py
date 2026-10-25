"""Router of the Settings screens (UF-BOT-06) and Log out (UF-BOT-10)."""

from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.common.settings.handlers.ask_logout import ask_logout
from app.interfaces.bot.routers.common.settings.handlers.logout import logout
from app.interfaces.bot.routers.common.settings.handlers.open_screen import open_screen
from app.interfaces.bot.routers.common.settings.handlers.set_preference import (
    set_preference,
)
from app.interfaces.bot.routers.common.settings.handlers.toggle_subject import (
    toggle_subject,
)
from app.interfaces.bot.settings_patch import SCREEN_OF_KEY
from app.shared.contracts.callbacks import MenuCb, SettingsCb

from aiogram import F, Router
from aiogram.filters import Command


def register_filters(router: Router) -> None:
    """Settings are for linked accounts."""
    router.message.filter(IsLinked())
    router.callback_query.filter(IsLinked())


def build_router() -> Router:
    """Build the settings router."""
    router = Router(name="common.settings")
    register_filters(router)
    router.message.register(open_screen, Command("settings"))
    router.callback_query.register(open_screen, MenuCb.filter(F.screen == "settings"))
    router.callback_query.register(open_screen, SettingsCb.filter(F.key == "open"))
    router.callback_query.register(
        set_preference, SettingsCb.filter(F.key.in_(set(SCREEN_OF_KEY)))
    )
    router.callback_query.register(
        toggle_subject, SettingsCb.filter(F.key == "subject")
    )
    router.callback_query.register(
        ask_logout, SettingsCb.filter((F.key == "logout") & (F.value == "ask"))
    )
    router.callback_query.register(
        logout, SettingsCb.filter((F.key == "logout") & (F.value == "yes"))
    )
    return router
