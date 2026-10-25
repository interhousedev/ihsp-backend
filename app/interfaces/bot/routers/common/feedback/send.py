"""Send: the report goes to the feedback module; the user gets a confirmation."""

from typing import Any
from uuid import UUID

from app.interfaces.bot.routers.common.feedback.rules import RATE_LIMITED_CODE
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def send_report(
    callback: CallbackQuery,
    state: FSMContext,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Submit the report and end the flow (also when the daily limit is reached)."""
    data = await state.get_data()
    await state.clear()
    files = [UUID(file_id) for file_id in data.get("files", [])]
    try:
        await container.feedback.submit(
            actor,
            data["kind"],
            data["area"],
            data["title"],
            data["description"],
            files,
            source="bot",
        )
    except BaseError as error:
        if error.code != RATE_LIMITED_CODE:
            raise
        text = i18n("bot-feedback-rate-limited")
    else:
        text = i18n("bot-feedback-sent")
    await show(callback, RenderedMessage(text_html=text, buttons=None))
