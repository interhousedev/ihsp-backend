"""A teacher sent a link: offer the lessons to attach it to (BOT-20, BOT-23)."""

from app.interfaces.bot.routers.teacher.resources.offer import offer_lessons
from app.interfaces.bot.services import BotServices
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def receive_url(
    message: Message,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Ask where to put the link; the link check happens in the links module."""
    content = {"kind": "url", "url": (message.text or "").strip()}
    await offer_lessons(
        message, state, content, user=user, services=services, i18n=i18n
    )
