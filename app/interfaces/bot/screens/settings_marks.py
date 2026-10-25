"""Mark notification settings screen (BOT-13)."""

from app.interfaces.bot.keyboards import settings_marks
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_settings_marks(prefs: UserPreferences, i18n: I18nContext) -> RenderedMessage:
    """Return the toggles for mark types, values and drop alerts."""
    return RenderedMessage(
        text_html=i18n("bot-settings-marks"), buttons=settings_marks.get(i18n, prefs)
    )
