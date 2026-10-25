"""Send on the preview: new email, reply or forward (MAIL-4, UF-MAIL-03/04)."""

from app.interfaces.bot.routers.student.mail.compose import load_draft
from app.interfaces.bot.screens.mail_preview import MailDraft
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def _send(draft: MailDraft, user: UserRef, services: BotServices) -> None:
    if draft.flow == "reply":
        await services.mail.reply(
            user.id, b64_to_uuid(draft.mail), html=draft.body_html
        )
    elif draft.flow == "forward":
        await services.mail.forward(
            user.id,
            b64_to_uuid(draft.mail),
            to=draft.to,
            note_html=draft.body_html or None,
        )
    else:
        await services.mail.send(
            user.id, to=draft.to, subject=draft.subject, html=draft.body_html
        )


async def send_draft(
    callback: CallbackQuery,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Send through the mail module; a limit error keeps the draft for a retry."""
    draft = await load_draft(state)
    if not draft.to:
        await state.clear()
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    await _send(draft, user, services)
    await state.clear()
    sent = RenderedMessage(
        text_html=i18n("bot-mail-sent", to=escape(", ".join(draft.to)))
    )
    await show(callback, sent)
