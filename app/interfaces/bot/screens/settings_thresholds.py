"""Alert threshold screen (BOT-12, BOT-13)."""

from app.interfaces.bot.keyboards import settings_thresholds
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_settings_thresholds(
    prefs: UserPreferences, i18n: I18nContext
) -> RenderedMessage:
    """Return the three threshold rows."""
    return RenderedMessage(
        text_html=i18n("bot-settings-thresholds"),
        buttons=settings_thresholds.get(i18n, prefs),
    )
