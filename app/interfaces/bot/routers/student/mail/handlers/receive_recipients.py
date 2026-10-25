"""The student sent the recipient addresses (new email and forward)."""

from dataclasses import replace

from app.interfaces.bot.routers.student.mail.compose import (
    ask,
    ask_note,
    load_draft,
    parse_recipients,
    save_draft,
)
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def receive_recipients(
    message: Message, state: FSMContext, services: BotServices, i18n: I18nContext
) -> None:
    """Validate the addresses (MAIL-6 limit), then ask for the next field."""
    addresses = parse_recipients(message.text or "")
    if addresses is None:
        await show(message, ask(i18n, "bot-mail-bad-address"))
        return
    limit = services.settings.limits.mail_recipients
    if len(addresses) > limit:
        await show(message, ask(i18n, "bot-mail-too-many", limit=limit))
        return
    draft = replace(await load_draft(state), to=tuple(addresses))
    if draft.flow == "forward":
        await save_draft(state, draft, MailStates.forward_note)
        await show(message, ask_note(i18n))
        return
    await save_draft(state, draft, MailStates.new_subject)
    await show(message, ask(i18n, "bot-mail-ask-subject"))
