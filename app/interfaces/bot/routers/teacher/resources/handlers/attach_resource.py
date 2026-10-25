"""Material / Attachment pressed: upload the file or check the link and attach it."""

import io
from typing import Literal

from app.interfaces.bot.routers.teacher.resources.offer import MAX_FILE_BYTES
from app.interfaces.bot.screens.resource_added import (
    build_resource_added,
    build_resource_refused,
)
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import answer_callback, show
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.callbacks import ResourceLessonCb
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.contracts.identity import UserRef
from app.shared.contracts.links import ResourceRef
from app.shared.i18n.core import I18nContext
from app.shared.ids import b64_to_uuid

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

Role = Literal["material", "attachment"]
ROLES: dict[str, Role] = {"m": "material", "a": "attachment"}


class FileTooLargeError(BaseError):
    """The file is over the 20 MB download limit of bots."""

    code = "bot/file-too-large"
    status = 413
    message_key = "bot-resource-too-large"


async def _download(bot: Bot, file_id: str) -> bytes:
    """Download a Telegram file into memory; refuse files over the limit."""
    buffer = io.BytesIO()
    try:
        await bot.download(file_id, destination=buffer)
    except TelegramBadRequest as error:
        if "too big" in error.message:
            raise FileTooLargeError from error
        raise
    data = buffer.getvalue()
    if len(data) > MAX_FILE_BYTES:
        raise FileTooLargeError
    return data


async def _attach(
    bot: Bot,
    content: dict[str, str],
    *,
    lesson: str,
    role: Role,
    user: UserRef,
    actor: Actor,
    services: BotServices,
) -> ResourceRef:
    lesson_id = b64_to_uuid(lesson)
    if content["kind"] == "url":
        return await services.links.add_lesson_resource(
            actor, lesson_id, role=role, url=content["url"]
        )
    stored = await services.files.store_bytes(
        owner_id=user.id,
        scope=FileScope.STAFF,
        purpose=FilePurpose.LINK,
        name=content["name"],
        data=await _download(bot, content["file_id"]),
    )
    return await services.links.add_lesson_resource(
        actor, lesson_id, role=role, file_id=stored.id
    )


async def attach_resource(
    callback: CallbackQuery,
    callback_data: ResourceLessonCb,
    bot: Bot,
    state: FSMContext,
    user: UserRef,
    actor: Actor,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Store the pending file or link on the chosen lesson and confirm."""
    content = await state.get_data()
    if "kind" not in content:
        await state.clear()
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    await state.clear()
    try:
        resource = await _attach(
            bot,
            content,
            lesson=callback_data.lesson,
            role=ROLES[callback_data.role],
            user=user,
            actor=actor,
            services=services,
        )
    except BaseError as error:
        text = i18n(error.message_key, **error.params)
    else:
        await show(callback, build_resource_added(resource, i18n, services.urls))
        return
    await show(callback, build_resource_refused(i18n, text, services.urls))
