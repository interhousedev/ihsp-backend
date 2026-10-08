"""Language picker screen."""

from app.interfaces.bot.keyboards import settings_language
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_settings_language(
    prefs: UserPreferences, i18n: I18nContext
) -> RenderedMessage:
    """Return the language choices with the current one checked."""
    return RenderedMessage(
        text_html=i18n("bot-settings-language"),
        buttons=settings_language.get(i18n, prefs.locale),
    )
