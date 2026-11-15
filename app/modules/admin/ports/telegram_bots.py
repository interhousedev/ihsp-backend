"""Ports of the Telegram bot registry: rows, members, tokens and getMe."""

from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from app.modules.admin.domain.telegram_bot import BotIdentity, TelegramBot


class BotRepository(Protocol):
    """Registered bots (``admin.telegram_bots``)."""

    async def list_all(self) -> list[TelegramBot]:
        """Every bot, the default first, then by creation time."""
        ...

    async def get(self, bot_id: UUID, *, for_update: bool = False) -> TelegramBot:
        """One bot or BotNotFoundError."""
        ...

    async def by_telegram_id(self, telegram_id: int) -> TelegramBot | None:
        """The bot registered with this Telegram id, if any."""
        ...

    async def add(self, bot: TelegramBot, *, actor_id: UUID | None) -> None:
        """Insert a bot."""
        ...

    async def save(self, bot: TelegramBot, *, actor_id: UUID | None) -> None:
        """Write the mutable fields back."""
        ...

    async def members(self, bot_id: UUID, user_ids: Collection[UUID]) -> set[UUID]:
        """Which of these users have written to the bot."""
        ...

    async def member_counts(self) -> dict[UUID, int]:
        """Linked users that have written to each bot."""
        ...


class BotTokenVault(Protocol):
    """The tokens, one Vault KV secret per bot; never in the database."""

    async def put(self, bot_id: UUID, token: str) -> None:
        """Store or replace the token (BotVaultUnavailableError when unreachable)."""
        ...

    async def get(self, bot_id: UUID) -> str | None:
        """The token, or None when it was never stored."""
        ...


class BotProbe(Protocol):
    """Asks Telegram who a token belongs to."""

    async def identify(self, token: str) -> BotIdentity:
        """getMe; BotTokenInvalidError when Telegram rejects the token."""
        ...
