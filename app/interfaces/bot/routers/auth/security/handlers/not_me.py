"""'This was not me': send the user to the security settings (UF-BOT-01, UF-BOT-02)."""

from app.interfaces.bot.keyboards import security_link
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import NotMeCb
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def not_me(
    callback: CallbackQuery,
    callback_data: NotMeCb,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Explain what to do and link the ID service's security page."""
    key = "bot-not-me-otp" if callback_data.kind == "otp" else "bot-not-me-tg"
    await show(
        callback,
        RenderedMessage(
            text_html=i18n(key), buttons=security_link.get(i18n, services.urls)
        ),
        new_message=True,
    )
