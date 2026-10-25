"""Open a settings screen: the Settings menu item, /settings and sub screens."""

from app.interfaces.bot.routers.common.settings.render import render_settings_screen
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MenuCb, SettingsCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def open_screen(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
    callback_data: SettingsCb | MenuCb | None = None,
) -> None:
    """Show the screen a button names; the menu and /settings show the overview."""
    screen = callback_data.value if isinstance(callback_data, SettingsCb) else "main"
    await show(request, await render_settings_screen(screen, user, services, i18n))
