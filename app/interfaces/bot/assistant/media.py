"""Photos and documents sent with a caption become files the assistant can read."""

import asyncio
import io
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.interfaces.bot.routers.teacher.resources.handlers.attach_resource import (
    FileTooLargeError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

MAX_FILE_BYTES = 20 * 1024 * 1024  # what bots may download
READY_TIMEOUT = 30.0  # seconds to wait for the files module's processing
POLL_INTERVAL = 1.0
READY = "ready"
REFUSED = frozenset({"rejected", "deleted"})

Sleep = Callable[[float], Awaitable[None]]


class FileNotReadyError(BaseError):
    """The upload was not processed in time (or was refused): nothing was asked."""

    code = "bot/ai-file-not-ready"
    status = 409
    message_key = "bot-ai-file-not-ready"


async def wait_ready(
    files: FilesApi,
    file_id: UUID,
    *,
    timeout: float = READY_TIMEOUT,
    sleep: Sleep = asyncio.sleep,
    now: Callable[[], float] = time.monotonic,
) -> None:
    """Poll until the file is ready; FileNotReadyError on refusal or timeout."""
    deadline = now() + timeout
    while True:
        ref = await files.get(file_id)
        status = None if ref is None else str(ref.status)
        if status == READY:
            return
        if status is None or status in REFUSED or now() >= deadline:
            raise FileNotReadyError()
        await sleep(POLL_INTERVAL)


async def download_capped(bot: Bot, file_id: str, *, size: int | None = None) -> bytes:
    """Download a Telegram file; FileTooLargeError above the 20 MB bot limit.

    `size` is the file size Telegram reports: a file over the limit is refused before
    any byte is downloaded. The size of the downloaded bytes is checked as well.
    """
    if size is not None and size > MAX_FILE_BYTES:
        raise FileTooLargeError
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


async def upload_media(
    bot: Bot,
    message: Message,
    actor: Actor,
    files: FilesApi,
    *,
    sleep: Sleep = asyncio.sleep,
) -> list[UUID]:
    """Store the message's photo or document, wait until it is processed.

    Returns the new file ids (the AI module accepts only ready files).
    """
    if message.photo:
        photo = message.photo[-1]
        file_id, size = photo.file_id, photo.file_size
        name = f"photo-{message.message_id}.jpg"
    elif message.document:
        file_id, size = message.document.file_id, message.document.file_size
        name = message.document.file_name or f"file-{message.message_id}"
    else:
        return []
    scope = FileScope.STUDENT if actor.has(Role.STUDENT) else FileScope.STAFF
    stored = await files.store_bytes(
        owner_id=actor.user_id,
        scope=scope,
        purpose=FilePurpose.AI_UPLOAD,
        name=name,
        data=await download_capped(bot, file_id, size=size),
    )
    await wait_ready(files, stored.id, sleep=sleep)
    return [stored.id]
