"""The mailbox: the last 10 emails, paged (MAIL-3, UF-MAIL-02)."""

from datetime import UTC, datetime

from app.interfaces.bot.screens.mail_list import PAGE_SIZE, build_mail_list
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MailListCb, MenuCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def show_mail_list(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
    callback_data: MailListCb | MenuCb | None = None,
) -> None:
    """Show one page; the Mail menu item and /mail open the newest."""
    before = callback_data.before if isinstance(callback_data, MailListCb) else 0
    cutoff = datetime.fromtimestamp(before, UTC) if before else None
    mails = await services.mail.recent(user.id, limit=PAGE_SIZE, before=cutoff)
    address = services.mail.address_of(user.login or "")
    rendered = build_mail_list(mails, address, i18n, is_first_page=before == 0)
    await show(request, rendered)
