"""The teacher sent the homework text: show it with Save, Edit, Cancel (BOT-18)."""

from app.interfaces.bot.routers.teacher.homework_prompt.states import HomeworkStates
from app.interfaces.bot.screens.homework_preview import build_homework_preview
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

HOMEWORK_MAX_CHARS = 2000


async def receive_homework_text(
    message: Message, state: FSMContext, i18n: I18nContext
) -> None:
    """Keep the text in the FSM and ask for confirmation."""
    text = (message.text or "").strip()
    if len(text) > HOMEWORK_MAX_CHARS:
        await message.answer(i18n("bot-homework-too-long", limit=HOMEWORK_MAX_CHARS))
        return
    data = await state.get_data()
    await state.set_state(HomeworkStates.confirm)
    await state.update_data(text=text)
    await show(message, build_homework_preview(b64_to_uuid(data["lesson"]), text, i18n))
