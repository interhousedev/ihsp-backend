"""The bot registry inside handlers: feature switches and who wrote to which bot."""

import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.modules.admin.domain.telegram_bot import BotFeature
from app.modules.admin.infrastructure.bot_registry import BotRegistryCache
from app.modules.admin.infrastructure.repositories.telegram_bots import touch_member
from app.shared.contracts.identity import UserRef

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.filters import Filter
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

MEMBER_TOUCH_SECONDS = 600.0
"""How often one (bot, user) pair is written; announcements tolerate the lag."""
_MAX_REMEMBERED = 50_000


class BotRegistryMiddleware(BaseMiddleware):
    """Adds ``bot_registry`` and records linked users per registered bot.

    Goes after ActorMiddleware (it reads ``user``).
    """

    def __init__(
        self,
        registry: BotRegistryCache,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Callable[[], Any],
    ) -> None:
        """`clock` returns the current aware datetime."""
        self.registry = registry
        self.sessionmaker = sessionmaker
        self.clock = clock
        self._touched: dict[tuple[UUID, int], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Expose the registry, then remember the member (never fails the update)."""
        data["bot_registry"] = self.registry
        bot: Bot | None = data.get("bot")
        from_user: TelegramUser | None = data.get("event_from_user")
        foreign_chat = getattr(event, "event_type", None) == "guest_message"
        if (
            bot is not None
            and from_user is not None
            and not from_user.is_bot
            and not foreign_chat
        ):
            try:
                await self._touch(bot.id, from_user.id, data.get("user"))
            except Exception:  # noqa: BLE001 - bookkeeping only
                log.warning("bot_member_touch_failed", exc_info=True)
        return await handler(event, data)

    async def _touch(
        self, telegram_bot_id: int, telegram_user_id: int, user: UserRef | None
    ) -> None:
        registered = await self.registry.by_telegram_id(telegram_bot_id)
        if registered is None:
            return
        key = (registered.id, telegram_user_id)
        now = time.monotonic()
        last = self._touched.get(key)
        if last is not None and now - last < MEMBER_TOUCH_SECONDS:
            return
        if len(self._touched) > _MAX_REMEMBERED:
            self._touched.clear()
        async with self.sessionmaker() as session:
            await touch_member(
                session,
                bot_id=registered.id,
                telegram_user_id=telegram_user_id,
                user_id=None if user is None else user.id,
                seen_at=self.clock(),
            )
            await session.commit()
        self._touched[key] = now  # only after the write landed


class BotAllows(Filter):
    """Passes when the bot handling the update has the feature switched on.

    Without a registry (tests, empty registry) every feature is allowed, as with
    the single bot before.
    """

    def __init__(self, feature: BotFeature) -> None:
        """The feature to check."""
        self.feature = feature

    async def __call__(
        self,
        event: TelegramObject,
        bot: Bot,
        bot_registry: BotRegistryCache | None = None,
    ) -> bool:
        """Ask the cached registry."""
        if bot_registry is None:
            return True
        return await bot_registry.allows(bot.id, self.feature)
