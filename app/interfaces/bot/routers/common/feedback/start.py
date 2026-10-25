"""/feedback and the main menu button: the flow starts with the kind."""

from app.interfaces.bot.routers.common.feedback import keyboards
from app.interfaces.bot.routers.common.feedback.states import FeedbackStates
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


async def start(
    request: Message | CallbackQuery, state: FSMContext, i18n: I18nContext
) -> None:
    """Begin a new report (an unfinished one is dropped)."""
    await state.clear()
    await state.set_state(FeedbackStates.kind)
    rendered = RenderedMessage(
        text_html=i18n("bot-feedback-ask-kind"), buttons=keyboards.kinds(i18n)
    )
    await show(request, rendered)
