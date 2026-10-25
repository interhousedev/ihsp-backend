"""Resolve the contract objects once per update."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.interfaces.bot.services import services_from_container

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ServicesMiddleware(BaseMiddleware):
    """Adds ``services`` (BotServices) built from the ``container`` kwarg."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Build the services from the container passed to the dispatcher."""
        data["services"] = services_from_container(data["container"])
        return await handler(event, data)
