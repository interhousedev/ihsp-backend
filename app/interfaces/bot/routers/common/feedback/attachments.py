"""Attachments of a report: each file is stored; Done or Skip ends the step."""

from typing import Any
from uuid import UUID

from app.interfaces.bot.assistant.media import FileNotReadyError
from app.interfaces.bot.routers.common.feedback import texts
from app.interfaces.bot.routers.common.feedback.callbacks import FeedbackStepCb
from app.interfaces.bot.routers.common.feedback.rules import MAX_FILES
from app.interfaces.bot.routers.common.feedback.states import FeedbackStates
from app.interfaces.bot.routers.common.feedback.upload import store_attachment
from app.interfaces.bot.routers.teacher.resources.handlers.attach_resource import (
    FileTooLargeError,
)
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


async def receive_file(
    message: Message,
    state: FSMContext,
    bot: Bot,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Store one more file (at most MAX_FILES) and say how many there are."""
    data = await state.get_data()
    stored: list[str] = list(data.get("files", []))
    if len(stored) >= MAX_FILES:
        await show(message, texts.attaching(i18n, "bot-feedback-too-many-files"))
        return
    try:
        file_id: UUID | None = await store_attachment(
            bot, message, actor, container.files.public
        )
    except FileTooLargeError:
        await show(message, texts.attaching(i18n, "bot-resource-too-large"))
        return
    except FileNotReadyError:
        await show(message, texts.attaching(i18n, "bot-feedback-file-failed"))
        return
    if file_id is None:
        await show(message, texts.attaching(i18n, "bot-feedback-attach-hint"))
        return
    stored.append(str(file_id))
    await state.update_data(files=stored)
    await show(
        message,
        texts.attaching(i18n, "bot-feedback-attached", count=len(stored)),
    )


async def hint_attachments(message: Message, i18n: I18nContext) -> None:
    """Text or a sticker where files are expected: the step stays open."""
    await show(message, texts.attaching(i18n, "bot-feedback-attach-hint"))


async def finish_attachments(
    callback: CallbackQuery,
    callback_data: FeedbackStepCb,
    state: FSMContext,
    i18n: I18nContext,
) -> None:
    """Done keeps the files sent; Skip sends the report without them."""
    if callback_data.action == "skip":
        await state.update_data(files=[])
    await state.set_state(FeedbackStates.confirm)
    await show(callback, texts.summary(await state.get_data(), i18n))
