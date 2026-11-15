"""Legal consent for the bot: no use of the bot until the documents are accepted."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.interfaces.bot.utilities.markup import to_markup, url_button
from app.shared.base_error import ForbiddenError
from app.shared.contracts.callbacks import NotMeCb, OtpCancelCb

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineQuery, Message, TelegramObject

# Security buttons protect the account: a user who has not accepted the documents
# can still cancel an OTP reset or report a sign-in that was not theirs.
_SECURITY_PREFIXES = frozenset({OtpCancelCb.__prefix__, NotMeCb.__prefix__})


def is_security_callback(data: str | None) -> bool:
    """True for the OTP-cancel and "not me" buttons."""
    return bool(data) and str(data).split(":", 1)[0] in _SECURITY_PREFIXES


async def consent_pending(data: dict[str, Any]) -> bool:
    """True when the linked user has not accepted the current legal documents."""
    actor = data.get("actor")
    legal = getattr(data["container"], "legal", None)
    if actor is None or legal is None:
        return False
    try:
        await legal.require_consent.execute(actor.user_id)
    except ForbiddenError:
        return True
    return False


class ConsentMiddleware(BaseMiddleware):
    """Answer a linked user who has not accepted the documents with a link."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Refuse messages, presses and inline queries while consent is pending."""
        if not isinstance(event, (Message, CallbackQuery, InlineQuery)):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and is_security_callback(event.data):
            return await handler(event, data)
        if not await consent_pending(data):
            return await handler(event, data)
        if isinstance(event, InlineQuery):
            await event.answer([], cache_time=0, is_personal=True)
            return None
        i18n = data["i18n"]
        text = i18n("bot-legal-acceptance-required")
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
            return None
        urls = data["services"].urls
        link = urls.page(data["actor"].roles, "")
        markup = to_markup([[url_button(i18n("bot-legal-accept-button"), link)]])
        await event.answer(text, reply_markup=markup)
        return None
