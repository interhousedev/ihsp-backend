"""Save: store the previewed homework on the lesson (BOT-18)."""

from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.contracts.callbacks import HomeworkPromptCb
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def save_homework(
    callback: CallbackQuery,
    callback_data: HomeworkPromptCb,
    state: FSMContext,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Call ``set_homework``; the due date is computed by classwork (None)."""
    text = str((await state.get_data()).get("text", ""))
    await services.classwork.set_homework(
        b64_to_uuid(callback_data.lesson), actor, text, None
    )
    await state.clear()
    saved = RenderedMessage(text_html=i18n("bot-homework-saved", text=escape(text)))
    await show(callback, saved)
