"""Log out confirmation (UF-BOT-10)."""

from app.interfaces.bot.keyboards import logout_confirm
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_logout_confirm(i18n: I18nContext) -> RenderedMessage:
    """Warn that OTP codes and notifications stop on this Telegram account."""
    return RenderedMessage(
        text_html=i18n("bot-logout-confirm"), buttons=logout_confirm.get(i18n)
    )
