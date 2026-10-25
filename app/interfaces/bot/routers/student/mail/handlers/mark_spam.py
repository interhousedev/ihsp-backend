"""Spam: mark the email and offer Undo (MAIL-5, UF-MAIL-04 step 3)."""

from app.interfaces.bot.keyboards import mail_spam_undo
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MailCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def mark_spam(
    callback: CallbackQuery,
    callback_data: MailCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Mark as spam and edit the message to "Marked as spam" with Undo."""
    mail_id = b64_to_uuid(callback_data.mail)
    await services.mail.mark_spam(user.id, mail_id, spam=True)
    await show(
        callback,
        RenderedMessage(
            text_html=i18n("bot-mail-marked-spam"),
            buttons=mail_spam_undo.get(i18n, mail_id),
        ),
    )
