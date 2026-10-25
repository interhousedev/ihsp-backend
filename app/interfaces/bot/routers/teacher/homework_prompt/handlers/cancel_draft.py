"""Cancel on the homework preview: drop the draft text."""

from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def cancel_homework(
    callback: CallbackQuery, state: FSMContext, i18n: I18nContext
) -> None:
    """Clear the FSM and tell the teacher nothing was saved."""
    await state.clear()
    await show(callback, RenderedMessage(text_html=i18n("bot-homework-cancelled")))
