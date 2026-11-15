"""Choice of the TelegramSender by `TELEGRAM__MODE`."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.modules.admin.domain.telegram_bot import BotFeature
from app.modules.admin.infrastructure.bot_registry import BotRegistryCache
from app.modules.admin.infrastructure.bot_token_vault import VaultBotTokenStore
from app.modules.notify.infrastructure.fake_sender import FakeTelegramSender
from app.modules.notify.infrastructure.telegram_sender import (
    AiogramTelegramSender,
    create_bot,
)
from app.settings import Settings
from app.shared.contracts.notify import BotRoute, TelegramSender

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

Closer = Callable[[], Awaitable[None]]


class MultiBotSender:
    """The default bot's sender that also routes to the other registered bots.

    Implements TelegramSender (always the default bot, as before the registry) and
    BotSenders. Senders of other bots are built lazily from their Vault tokens and
    rebuilt when the bot row changes (``updated_at``, bumped by a rotation).
    """

    def __init__(
        self,
        default: TelegramSender,
        *,
        registry: BotRegistryCache,
        vault: VaultBotTokenStore,
        make: Callable[[str], TelegramSender],
    ) -> None:
        """`make` builds a sender from a token."""
        self._default = default
        self._registry = registry
        self._vault = vault
        self._make = make
        self._senders: dict[UUID, tuple[str, TelegramSender]] = {}
        self._lock = asyncio.Lock()

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        """Through the default bot."""
        return await self._default.send_message(chat_id, text_html, buttons)

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption_html: str | None = None,
    ) -> int:
        """Through the default bot."""
        return await self._default.send_document(chat_id, filename, data, caption_html)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Through the default bot."""
        await self._default.delete_message(chat_id, message_id)

    async def route(self, bot_id: str | None, *, personal: bool) -> BotRoute | None:
        """The sender of a bot whose switch allows this kind of message."""
        feature = BotFeature.NOTIFICATIONS if personal else BotFeature.ANNOUNCEMENTS
        bots = await self._registry.all()
        if bot_id is None:
            default = next((bot for bot in bots if bot.is_default), None)
            if default is not None and not default.has(feature):
                return None
            return BotRoute(sender=self._default, is_default=True)
        try:
            bot = await self._registry.get(UUID(bot_id))
        except ValueError:
            return None
        if bot is None or not bot.has(feature):
            return None
        if bot.is_default:
            return BotRoute(sender=self._default, is_default=True)
        sender = await self._sender_of(bot.id, bot.updated_at.isoformat())
        return None if sender is None else BotRoute(sender=sender, is_default=False)

    async def _sender_of(self, bot_id: UUID, version: str) -> TelegramSender | None:
        async with self._lock:
            cached = self._senders.get(bot_id)
            if cached is not None and cached[0] == version:
                return cached[1]
            try:
                token = await self._vault.get(bot_id)
            except Exception:  # noqa: BLE001 - Vault down: retry next time
                log.warning("bot_token_unavailable", bot_id=str(bot_id))
                return None
            if token is None:
                return None
            if cached is not None:
                await _close(cached[1])
            sender = self._make(token)
            self._senders[bot_id] = (version, sender)
            return sender

    async def close(self) -> None:
        """Close the other bots' sessions (the default one has its own closer)."""
        for _, sender in self._senders.values():
            await _close(sender)
        self._senders.clear()


async def _close(sender: TelegramSender) -> None:
    close = getattr(sender, "close", None)
    if close is not None:
        await close()


def make_multi_bot_sender(
    settings: Settings,
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[TelegramSender, list[Closer]]:
    """The default sender wrapped with the bot registry."""
    default, closer = make_telegram_sender(settings, redis)
    if settings.telegram.mode == "fake":

        def make(token: str) -> TelegramSender:
            return FakeTelegramSender(redis)

    else:

        def make(token: str) -> TelegramSender:
            return AiogramTelegramSender(create_bot(token))

    multi = MultiBotSender(
        default,
        registry=BotRegistryCache(sessionmaker),
        vault=VaultBotTokenStore(settings.bot_vault),
        make=make,
    )
    closers: list[Closer] = [multi.close]
    if closer is not None:
        closers.append(closer)
    return multi, closers


def make_telegram_sender(
    settings: Settings, redis: Redis
) -> tuple[TelegramSender, Closer | None]:
    """Return the sender and, for the real one, the coroutine that closes its bot.

    `fake` never touches the network: messages go to the Redis list
    `fake-telegram:outbox`. `polling` and `webhook` send through the Bot API.
    """
    if settings.telegram.mode == "fake":
        return FakeTelegramSender(redis), None
    sender = AiogramTelegramSender(
        create_bot(settings.telegram.bot_token.get_secret_value())
    )
    return sender, sender.close
