"""Add homework / Edit: ask the teacher to send the text (BOT-18)."""

from app.interfaces.bot.keyboards import cancel
from app.interfaces.bot.routers.teacher.homework_prompt.states import HomeworkStates
from app.interfaces.bot.routers.teacher.prompt_flow import load_state
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import HomeworkPromptCb
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def ask_homework(
    callback: CallbackQuery,
    callback_data: HomeworkPromptCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Wait for a text message; the prompt itself stays where it is (new message)."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    if (
        await load_state(
            callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
        )
        is None
    ):
        return
    await state.set_state(HomeworkStates.waiting_text)
    await state.update_data(lesson=callback_data.lesson)
    ask = RenderedMessage(text_html=i18n("bot-homework-ask"), buttons=cancel.get(i18n))
    await show(callback, ask, new_message=callback_data.action == "add")
