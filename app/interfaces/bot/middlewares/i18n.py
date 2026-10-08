"""Pick the language of the conversation and expose ``i18n`` to handlers."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.shared.contracts.identity import UserRef

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

SUPPORTED_LOCALES = ("uz", "ru", "en")
DEFAULT_LOCALE = "ru"


def resolve_locale(user: UserRef | None, from_user: User | None) -> str:
    """Return the user's preference, else Telegram's language, else ``ru``."""
    if user is not None and user.locale in SUPPORTED_LOCALES:
        return user.locale
    code = (from_user.language_code if from_user else None) or ""
    short = code.lower().split("-")[0]
    return short if short in SUPPORTED_LOCALES else DEFAULT_LOCALE


class I18nMiddleware(BaseMiddleware):
    """Adds ``locale`` and ``i18n`` (needs ``user`` and ``services`` in data)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Resolve the locale from the update's sender, never from the event."""
        locale = resolve_locale(data.get("user"), data.get("event_from_user"))
        data["locale"] = locale
        data["i18n"] = data["services"].i18n.get_context(locale)
        return await handler(event, data)
