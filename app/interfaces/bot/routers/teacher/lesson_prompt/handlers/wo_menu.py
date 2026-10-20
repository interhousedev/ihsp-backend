"""Work-off: choose. List the teacher's templates with None (WO-5)."""

from app.interfaces.bot.callbacks import WorkOffPromptCb
from app.interfaces.bot.keyboards import work_off_pick
from app.interfaces.bot.routers.teacher.prompt_flow import load_state
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.interfaces.bot.work_off_choice import load_choice
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def open_work_off_menu(
    callback: CallbackQuery,
    callback_data: WorkOffPromptCb,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Edit the prompt into the template list; the lesson is re-read first."""
    lesson_id = b64_to_uuid(callback_data.lesson)
    if (
        await load_state(
            callback, user=user, lesson_id=lesson_id, services=services, i18n=i18n
        )
        is None
    ):
        return
    choice = await load_choice(state, services, user.id, callback_data.lesson)
    key = "bot-work-off-pick" if choice.templates else "bot-work-off-no-templates"
    rows = work_off_pick.get(i18n, lesson_id, choice)
    await show(callback, RenderedMessage(text_html=i18n(key), buttons=rows))
