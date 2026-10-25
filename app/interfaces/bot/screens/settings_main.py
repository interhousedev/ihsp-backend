"""Settings overview (UF-BOT-06)."""

from app.interfaces.bot.keyboards import settings_language, settings_main
from app.shared.contracts.identity import UserPreferences, UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_settings_main(
    user: UserRef, prefs: UserPreferences, i18n: I18nContext
) -> RenderedMessage:
    """Return the settings menu for the user's roles."""
    names = dict(settings_language.LANGUAGES)
    text = i18n("bot-settings-main", language=names.get(prefs.locale, prefs.locale))
    return RenderedMessage(text_html=text, buttons=settings_main.get(i18n, user.roles))
