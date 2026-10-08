"""Open an email from the list: show it again with its buttons (UF-MAIL-02)."""

from app.interfaces.bot.screens.mail_message import build_mail_message, parse_mail_view
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MailCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.types import CallbackQuery


async def open_mail(
    callback: CallbackQuery,
    callback_data: MailCb,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Send the email as a new message so the list stays above it."""
    view = parse_mail_view(
        await services.mail.view(user.id, b64_to_uuid(callback_data.mail))
    )
    names = [attachment.name for attachment in view.attachments]
    await show(
        callback, build_mail_message(view, i18n, listed_names=names), new_message=True
    )
