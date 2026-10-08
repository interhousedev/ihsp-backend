"""New email: ask for the recipient (UF-MAIL-03 step 1)."""

from app.interfaces.bot.routers.student.mail.compose import ask, save_draft
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.screens.mail_preview import MailDraft
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def start_new_mail(
    callback: CallbackQuery, state: FSMContext, i18n: I18nContext
) -> None:
    """Begin a new draft."""
    await save_draft(state, MailDraft(flow="new"), MailStates.new_to)
    await show(callback, ask(i18n, "bot-mail-ask-to"), new_message=True)
