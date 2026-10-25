"""A file or voice message where text is expected in a mail flow."""

from app.interfaces.bot.routers.student.mail.compose import ask
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.types import Message


async def reject_non_text(message: Message, i18n: I18nContext) -> None:
    """Ask for text; the step stays open."""
    await show(message, ask(i18n, "bot-mail-text-only"))
