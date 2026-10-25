"""Save one setting and show its screen again (UF-BOT-06 step 4)."""

from app.interfaces.bot.routers.common.settings.render import render_settings_screen
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.settings_patch import SCREEN_OF_KEY, preference_patch
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.shared.contracts.callbacks import SettingsCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def set_preference(
    callback: CallbackQuery,
    callback_data: SettingsCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Apply the change through identity and re-render with the new state."""
    prefs = await services.directory.get_preferences(user.id)
    patch = preference_patch(prefs, callback_data.key, callback_data.value)
    if patch is None:
        await answer_callback(callback)
        return
    await services.identity_commands.update_preferences(user.id, patch)
    locale = patch.get("locale")
    if isinstance(locale, str):
        i18n = services.i18n.get_context(locale)  # show the screen in the new language
    screen = SCREEN_OF_KEY[callback_data.key]
    await show(callback, await render_settings_screen(screen, user, services, i18n))
