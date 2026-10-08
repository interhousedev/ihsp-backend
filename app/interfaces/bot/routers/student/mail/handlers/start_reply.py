"""Reply: ask for the text of the reply (UF-MAIL-04 step 1)."""

from app.interfaces.bot.routers.student.mail.compose import ask, save_draft
from app.interfaces.bot.routers.student.mail.states import MailStates
from app.interfaces.bot.screens.mail_message import parse_mail_view
from app.interfaces.bot.screens.mail_preview import MailDraft
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import MailCb
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def start_reply(
    callback: CallbackQuery,
    callback_data: MailCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Remember the email being answered and wait for the body."""
    view = parse_mail_view(
        await services.mail.view(user.id, b64_to_uuid(callback_data.mail))
    )
    subject = view.summary.subject
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    sender = view.summary.from_address
    draft = MailDraft(
        flow="reply", to=(sender,), subject=reply_subject, mail=callback_data.mail
    )
    await save_draft(state, draft, MailStates.reply_body)
    question = ask(
        i18n, "bot-mail-ask-reply", sender=escape(sender), subject=escape(reply_subject)
    )
    await show(callback, question, new_message=True)
