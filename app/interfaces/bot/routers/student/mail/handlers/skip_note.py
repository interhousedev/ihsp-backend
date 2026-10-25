"""Skip the note of a forward and show the preview."""

from dataclasses import replace

from app.interfaces.bot.routers.student.mail.compose import load_draft, save_draft
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.screens.mail_preview import build_mail_preview
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def skip_note(
    callback: CallbackQuery, state: FSMContext, i18n: I18nContext
) -> None:
    """Forward without a note."""
    draft = replace(await load_draft(state), body_html="")
    await save_draft(state, draft, MailStates.preview)
    await show(callback, build_mail_preview(draft, i18n))
