"""getMe probes and the cached registry the bot and worker processes read."""

import asyncio
import time
from uuid import UUID

from app.modules.admin.domain.errors import (
    BotTelegramUnavailableError,
    BotTokenInvalidError,
)
from app.modules.admin.domain.telegram_bot import (
    BotFeature,
    BotIdentity,
    TelegramBot,
    token_bot_id,
)
from app.modules.admin.infrastructure.repositories.telegram_bots import (
    SqlBotRepository,
)

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramUnauthorizedError,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

REFRESH_SECONDS = 30.0
STALE_SECONDS = 300.0
"""Without a good read for this long, only the default bot keeps its features."""


class AiogramBotProbe:
    """Implements `BotProbe` with a short-lived aiogram Bot."""

    async def identify(self, token: str) -> BotIdentity:
        """getMe; a rejected or malformed token is BotTokenInvalidError."""
        token_bot_id(token)
        bot = Bot(token.strip())
        try:
            me = await bot.get_me()
        except (TelegramUnauthorizedError, TelegramNotFound) as exc:
            raise BotTokenInvalidError(support_details="getMe: unauthorized") from exc
        except (TelegramNetworkError, TelegramAPIError) as exc:
            # Telegram unreachable, overloaded or limiting: the token may be fine.
            raise BotTelegramUnavailableError(
                support_details=f"getMe: {type(exc).__name__}"
            ) from exc
        finally:
            await bot.session.close()
        return BotIdentity(
            telegram_id=me.id, username=me.username or "", first_name=me.first_name
        )


class FakeBotProbe:
    """`TELEGRAM__MODE=fake`: the id comes from the token, no network."""

    async def identify(self, token: str) -> BotIdentity:
        """Derive a stable identity from the token prefix."""
        telegram_id = token_bot_id(token)
        return BotIdentity(
            telegram_id=telegram_id,
            username=f"bot{telegram_id}",
            first_name=f"Bot {telegram_id}",
        )


class BotRegistryCache:
    """The registry, reloaded at most every 30 seconds.

    Failure policy, on purpose: a failed reload keeps the last good copy, so a
    short database hiccup switches nothing off. After ``STALE_SECONDS`` without a
    good read the cache fails closed for every bot except the default one: the
    other bots lose all features (and so cannot be used after being disabled),
    while the default bot (or the env bot, ``default_telegram_id``) keeps working
    as the single bot did before.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        ttl: float = REFRESH_SECONDS,
        stale_after: float = STALE_SECONDS,
        default_telegram_id: int | None = None,
    ) -> None:
        """Nothing is read until the first call."""
        self._sessionmaker = sessionmaker
        self._ttl = ttl
        self._stale_after = stale_after
        self._default_telegram_id = default_telegram_id
        self._bots: dict[UUID, TelegramBot] = {}
        self._by_telegram: dict[int, TelegramBot] = {}
        self._loaded_at: float | None = None
        self._good_at: float | None = None
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        now = time.monotonic()
        if self._loaded_at is not None and now - self._loaded_at < self._ttl:
            return
        async with self._lock:
            if self._loaded_at is not None and now - self._loaded_at < self._ttl:
                return
            try:
                async with self._sessionmaker() as session:
                    bots = await SqlBotRepository(session).list_all()
            except Exception:  # noqa: BLE001 - keep serving the last copy
                log.warning("bot_registry_refresh_failed", exc_info=True)
                self._loaded_at = now
                return
            self._bots = {bot.id: bot.snapshot() for bot in bots}
            self._by_telegram = {bot.telegram_id: bot for bot in self._bots.values()}
            self._loaded_at = self._good_at = now

    def _stale(self) -> bool:
        return (
            self._good_at is None
            or time.monotonic() - self._good_at >= self._stale_after
        )

    def _trusted(self, bot: TelegramBot | None) -> TelegramBot | None:
        """The bot, unless the copy is stale and it is not the default bot."""
        if bot is None or bot.is_default or not self._stale():
            return bot
        return None

    def invalidate(self) -> None:
        """Reload on the next call (after an admin change in this process)."""
        self._loaded_at = None

    async def all(self) -> list[TelegramBot]:
        """Every registered bot (only the default one while the copy is stale)."""
        await self._refresh()
        return [bot for bot in self._bots.values() if self._trusted(bot)]

    async def get(self, bot_id: UUID) -> TelegramBot | None:
        """One bot by registry id."""
        await self._refresh()
        return self._trusted(self._bots.get(bot_id))

    async def by_telegram_id(self, telegram_id: int) -> TelegramBot | None:
        """One bot by its Telegram id (``bot.id`` in aiogram)."""
        await self._refresh()
        return self._trusted(self._by_telegram.get(telegram_id))

    async def allows(self, telegram_id: int, feature: BotFeature) -> bool:
        """Whether this Telegram bot may use the feature.

        A bot missing from a fresh registry (an empty registry, the env-token
        fallback) behaves like the single bot did before: everything is allowed.
        With a stale copy only the default or env bot is allowed anything.
        """
        bot = await self.by_telegram_id(telegram_id)
        if bot is not None:
            return bot.has(feature)
        return not self._stale() or telegram_id == self._default_telegram_id
