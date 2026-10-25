"""A voice message or file where text is expected (UF-BOT-08 alternative 5a)."""

from app.interfaces.bot.keyboards import cancel
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.types import Message


async def reject_non_text(message: Message, i18n: I18nContext) -> None:
    """Ask for text instead; the input stays open."""
    await show(
        message,
        RenderedMessage(
            text_html=i18n("bot-homework-text-only"), buttons=cancel.get(i18n)
        ),
    )
