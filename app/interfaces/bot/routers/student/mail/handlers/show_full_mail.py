"""Show full: the whole text of an email whose body was cut (MAIL-2)."""

from app.interfaces.bot.screens.mail_message import parse_mail_view
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MailCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def show_full_mail(
    callback: CallbackQuery,
    callback_data: MailCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Send the plain text in as many messages as needed."""
    view = parse_mail_view(
        await services.mail.view(user.id, b64_to_uuid(callback_data.mail))
    )
    title = escape(view.summary.subject or i18n("bot-mail-no-subject"))
    text = f"<b>{title}</b>\n\n{escape(view.text)}"
    await show(callback, RenderedMessage(text_html=text), new_message=True)
