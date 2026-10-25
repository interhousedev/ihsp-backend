"""A teacher sent a document: offer the lessons to attach it to (BOT-20, BOT-23)."""

from app.interfaces.bot.routers.teacher.resources.offer import (
    MAX_FILE_BYTES,
    offer_lessons,
)
from app.interfaces.bot.screens.resource_added import build_resource_refused
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def receive_document(
    message: Message,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Refuse files over 20 MB (staff portal link); otherwise ask where it goes."""
    document = message.document
    if document is None:
        return
    if document.file_size and document.file_size > MAX_FILE_BYTES:
        await state.clear()
        refused = build_resource_refused(
            i18n, i18n("bot-resource-too-large"), services.urls
        )
        await show(message, refused)
        return
    content = {
        "kind": "file",
        "file_id": document.file_id,
        "name": document.file_name or "file",
    }
    await offer_lessons(
        message, state, content, user=user, services=services, i18n=i18n
    )
