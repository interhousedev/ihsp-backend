"""Kind, area, title and description of a report; text where text is expected."""

from app.interfaces.bot.routers.common.feedback import keyboards, texts
from app.interfaces.bot.routers.common.feedback.callbacks import (
    FeedbackAreaCb,
    FeedbackKindCb,
)
from app.interfaces.bot.routers.common.feedback.rules import (
    DESCRIPTION_MAX_CHARS,
    TITLE_MAX_CHARS,
)
from app.interfaces.bot.routers.common.feedback.states import FeedbackStates
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


async def pick_kind(
    callback: CallbackQuery,
    callback_data: FeedbackKindCb,
    state: FSMContext,
    i18n: I18nContext,
) -> None:
    """Keep the kind and ask for the area."""
    await state.update_data(kind=callback_data.kind)
    await state.set_state(FeedbackStates.area)
    rendered = RenderedMessage(
        text_html=i18n("bot-feedback-ask-area"), buttons=keyboards.areas(i18n)
    )
    await show(callback, rendered)


async def pick_area(
    callback: CallbackQuery,
    callback_data: FeedbackAreaCb,
    state: FSMContext,
    i18n: I18nContext,
) -> None:
    """Keep the area and ask for the title."""
    await state.update_data(area=callback_data.area)
    await state.set_state(FeedbackStates.title)
    await show(callback, texts.ask(i18n, "bot-feedback-ask-title"))


async def receive_title(message: Message, state: FSMContext, i18n: I18nContext) -> None:
    """Keep a one-line title and ask for the description."""
    title = " ".join((message.text or "").split())
    if not title or len(title) > TITLE_MAX_CHARS:
        await show(
            message,
            texts.ask(i18n, "bot-feedback-bad-title", limit=TITLE_MAX_CHARS),
        )
        return
    await state.update_data(title=title)
    await state.set_state(FeedbackStates.description)
    await show(message, texts.ask(i18n, "bot-feedback-ask-description"))


async def receive_description(
    message: Message, state: FSMContext, i18n: I18nContext
) -> None:
    """Keep the description and ask for attachments."""
    description = (message.text or "").strip()
    if not description or len(description) > DESCRIPTION_MAX_CHARS:
        await show(
            message,
            texts.ask(
                i18n, "bot-feedback-bad-description", limit=DESCRIPTION_MAX_CHARS
            ),
        )
        return
    await state.update_data(description=description, files=[])
    await state.set_state(FeedbackStates.attachments)
    await show(message, texts.attaching(i18n, "bot-feedback-ask-files"))


async def use_buttons(message: Message, i18n: I18nContext) -> None:
    """Text where a button is expected: the step stays open."""
    await show(message, texts.ask(i18n, "bot-feedback-use-buttons"))


async def reject_non_text(message: Message, i18n: I18nContext) -> None:
    """A file or a sticker where text is expected: the step stays open."""
    await show(message, texts.ask(i18n, "bot-feedback-text-only"))
