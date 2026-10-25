"""The student sent the subject of a new email."""

from dataclasses import replace

from app.interfaces.bot.routers.student.mail.compose import (
    SUBJECT_MAX_CHARS,
    ask,
    load_draft,
    save_draft,
)
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def receive_subject(
    message: Message, state: FSMContext, i18n: I18nContext
) -> None:
    """Keep the subject and ask for the body."""
    subject = " ".join((message.text or "").split())
    if not subject or len(subject) > SUBJECT_MAX_CHARS:
        await show(message, ask(i18n, "bot-mail-bad-subject", limit=SUBJECT_MAX_CHARS))
        return
    draft = replace(await load_draft(state), subject=subject)
    await save_draft(state, draft, MailStates.new_body)
    await show(message, ask(i18n, "bot-mail-ask-body"))
