"""Add text: wait for the extra work-off text of the lesson (WO-5)."""

from app.interfaces.bot.callbacks import WorkOffPromptCb
from app.interfaces.bot.keyboards import work_off_text_cancel
from app.interfaces.bot.routers.teacher.lesson_prompt.states import WorkOffStates
from app.interfaces.bot.routers.teacher.prompt_flow import load_state
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def ask_work_off_text(
    callback: CallbackQuery,
    callback_data: WorkOffPromptCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Edit the prompt into a request for text, with Cancel."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    if (
        await load_state(
            callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
        )
        is None
    ):
        return
    await state.set_state(WorkOffStates.waiting_text)
    await state.update_data(work_off_lesson=callback_data.lesson)
    ask = RenderedMessage(
        text_html=i18n("bot-work-off-ask-text"),
        buttons=work_off_text_cancel.get(i18n, callback_data.lesson),
    )
    await show(callback, ask)
