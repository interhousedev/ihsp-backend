"""The student sent the body (new email) or the reply text; show the preview."""

from dataclasses import replace

from app.interfaces.bot.routers.student.mail.compose import load_draft, save_draft
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.screens.mail_preview import build_mail_preview
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def receive_body(message: Message, state: FSMContext, i18n: I18nContext) -> None:
    """Keep Telegram formatting as HTML (``html_text``) and show Send, Edit, Cancel."""
    draft = replace(await load_draft(state), body_html=message.html_text)
    await save_draft(state, draft, MailStates.preview)
    await show(message, build_mail_preview(draft, i18n))
