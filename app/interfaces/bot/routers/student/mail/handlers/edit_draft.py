"""Edit on the preview: send the text again (UF-MAIL-03 step 2)."""

from app.interfaces.bot.routers.student.mail.compose import (
    ask,
    ask_note,
    load_draft,
    save_draft,
)
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def edit_draft(
    callback: CallbackQuery, state: FSMContext, i18n: I18nContext
) -> None:
    """Go back to the last text input of the flow."""
    draft = await load_draft(state)
    if draft.flow == "forward":
        await save_draft(state, draft, MailStates.forward_note)
        await show(callback, ask_note(i18n))
    elif draft.flow == "reply":
        await save_draft(state, draft, MailStates.reply_body)
        question = ask(
            i18n,
            "bot-mail-ask-reply",
            sender=escape(", ".join(draft.to)),
            subject=escape(draft.subject),
        )
        await show(callback, question)
    else:
        await save_draft(state, draft, MailStates.new_body)
        await show(callback, ask(i18n, "bot-mail-ask-body"))
