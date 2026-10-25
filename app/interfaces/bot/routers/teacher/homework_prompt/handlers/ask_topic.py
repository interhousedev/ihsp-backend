"""Set topic: ask the teacher to send the lesson topic (BOT-17, ACA-21)."""

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


async def ask_topic(
    callback: CallbackQuery,
    callback_data: HomeworkPromptCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Wait for a text message with the topic."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    if (
        await load_state(
            callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
        )
        is None
    ):
        return
    await state.set_state(HomeworkStates.waiting_topic)
    await state.update_data(lesson=callback_data.lesson)
    ask = RenderedMessage(text_html=i18n("bot-topic-ask"), buttons=cancel.get(i18n))
    await show(callback, ask, new_message=True)
