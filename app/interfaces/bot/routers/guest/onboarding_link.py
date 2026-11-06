"""``/start link_<code>``: the deep link of the registration's Telegram step."""

from typing import Any

from app.modules.identity.application.telegram_onboarding import (
    DEEP_LINK_PREFIX,
    LinkOutcome,
)
from app.modules.identity.ports.init_data_verifier import InitDataUser
from app.shared.i18n.core import I18nContext

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

_KEYS = {
    LinkOutcome.LINKED: "bot-onboarding-linked",
    LinkOutcome.EXPIRED: "bot-onboarding-expired",
    LinkOutcome.LINKED_ELSEWHERE: "bot-onboarding-linked-elsewhere",
}


async def redeem_link(
    message: Message, command: CommandObject, container: Any, i18n: I18nContext
) -> None:
    """Redeem the one-time code for the Telegram account that sent it."""
    sender = message.from_user
    if sender is None or command.args is None:
        return
    outcome = await container.identity.auth.telegram_onboarding.redeem(
        command.args.removeprefix(DEEP_LINK_PREFIX),
        InitDataUser(
            id=sender.id,
            first_name=sender.first_name,
            last_name=sender.last_name,
            username=sender.username,
            language_code=sender.language_code,
        ),
    )
    await message.answer(i18n(_KEYS[outcome]))


def build_router() -> Router:
    """Registered first: this /start must win over every other /start handler."""
    router = Router(name="onboarding-link")
    router.message.register(
        redeem_link,
        CommandStart(deep_link=True, magic=F.args.startswith(DEEP_LINK_PREFIX)),
    )
    return router
