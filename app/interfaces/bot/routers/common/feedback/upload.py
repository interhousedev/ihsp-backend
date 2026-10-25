"""Attachments of a report: downloaded from Telegram, kept by the files module."""

from uuid import UUID

from app.interfaces.bot.assistant.media import (
    MAX_FILE_BYTES,
    download_capped,
    wait_ready,
)
from app.interfaces.bot.routers.teacher.resources.handlers.attach_resource import (
    FileTooLargeError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope

from aiogram import Bot
from aiogram.types import Message


def _media(message: Message) -> tuple[str, str, int | None] | None:
    """Telegram file id, a name and the size (when Telegram says) of the media."""
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, f"photo-{message.message_id}.jpg", photo.file_size
    if message.document:
        document = message.document
        name = document.file_name or f"file-{message.message_id}"
        return document.file_id, name, document.file_size
    if message.video:
        video = message.video
        name = video.file_name or f"video-{message.message_id}.mp4"
        return video.file_id, name, video.file_size
    return None


async def store_attachment(
    bot: Bot, message: Message, actor: Actor, files: FilesApi
) -> UUID | None:
    """Store the photo, document or video; wait until the files module has it.

    Raises FileTooLargeError above 20 MB and FileNotReadyError when the file is
    refused or not processed in time. Returns None for other messages.
    """
    media = _media(message)
    if media is None:
        return None
    file_id, name, size = media
    if size is not None and size > MAX_FILE_BYTES:
        raise FileTooLargeError()
    scope = FileScope.STUDENT if actor.has(Role.STUDENT) else FileScope.STAFF
    stored = await files.store_bytes(
        owner_id=actor.user_id,
        scope=scope,
        purpose=FilePurpose.FEEDBACK,
        name=name,
        data=await download_capped(bot, file_id, size=size),
    )
    await wait_ready(files, stored.id)
    return stored.id
