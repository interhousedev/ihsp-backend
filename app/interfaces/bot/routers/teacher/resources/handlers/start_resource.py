"""Current lesson -> Add resource: ask for a file or a link (UF-BOT-09)."""

from app.interfaces.bot.routers.teacher.resources.states import ResourceStates
from app.interfaces.bot.screens.resource_pick import build_resource_ask
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.callbacks import ResourceLessonCb
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def start_resource(
    callback: CallbackQuery,
    callback_data: ResourceLessonCb,
    state: FSMContext,
    i18n: I18nContext,
) -> None:
    """Remember the lesson and wait for the content."""
    await state.set_state(ResourceStates.waiting_content)
    await state.set_data({"lesson": callback_data.lesson})
    await show(callback, build_resource_ask(i18n), new_message=True)
