"""Telegram bots of the platform: the registry entry and its feature switches.

The token is never part of the entity: it lives in Vault (one KV path per bot) and
only its last four characters are kept as a hint for Administration.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.admin.domain.errors import (
    BotDefaultLockedError,
    BotFeatureUnknownError,
    BotNameInvalidError,
    BotTokenInvalidError,
    BotTokenMismatchError,
)

NAME_MAX = 64
TOKEN_HINT_LENGTH = 4


class BotFeature(StrEnum):
    """What a bot does; each switch gates handlers or senders at runtime."""

    AI_AGENT = "ai_agent"
    """The assistant for linked users (free text, /new, /delete)."""
    OPEN_AI_AGENT = "open_ai_agent"
    """The assistant for guests (not linked Telegram users)."""
    COMMANDS = "commands"
    """The published command menu (setMyCommands)."""
    NOTIFICATIONS = "notifications"
    """Personal notifications go out through this bot."""
    ANNOUNCEMENTS = "announcements"
    """Administration may send announcements through this bot."""
    MINI_APP = "mini_app"
    """The chat menu button keeps the Mini App (otherwise reset to the default)."""


ALL_FEATURES: frozenset[BotFeature] = frozenset(BotFeature)
"""What the single env bot did before the registry: everything."""


def parse_features(raw: dict[str, Any]) -> dict[BotFeature, bool]:
    """Validate a features mapping from storage or a request; unknown keys fail."""
    parsed: dict[BotFeature, bool] = {}
    for key, value in raw.items():
        try:
            feature = BotFeature(key)
        except ValueError as exc:
            raise BotFeatureUnknownError(params={"feature": str(key)}) from exc
        parsed[feature] = bool(value)
    return parsed


def token_bot_id(token: str) -> int:
    """The numeric bot id that starts every BotFather token (``<id>:<secret>``)."""
    head, sep, secret = token.strip().partition(":")
    if not sep or not head.isdigit() or len(secret) < 20:
        raise BotTokenInvalidError(support_details="malformed token")
    return int(head)


def token_hint(token: str) -> str:
    """The masked hint shown to Administration: the last four characters."""
    return token.strip()[-TOKEN_HINT_LENGTH:]


def check_name(name: str) -> str:
    """A display name of 1 to 64 characters."""
    cleaned = name.strip()
    if not cleaned or len(cleaned) > NAME_MAX:
        raise BotNameInvalidError(params={"max": NAME_MAX})
    return cleaned


@dataclass(frozen=True, slots=True)
class BotIdentity:
    """What Telegram's getMe says about a token."""

    telegram_id: int
    username: str
    first_name: str


@dataclass(slots=True)
class TelegramBot:
    """One registered bot."""

    id: UUID
    name: str
    username: str
    telegram_id: int
    token_hint: str
    enabled: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime
    features: dict[BotFeature, bool] = field(default_factory=dict)

    def has(self, feature: BotFeature) -> bool:
        """True when the bot is enabled and the switch is on.

        A switch the default bot has no stored value for is on (it does everything
        the single bot did, also features added later); for other bots it is off.
        """
        return self.enabled and self.features.get(feature, self.is_default)

    def set_enabled(self, enabled: bool) -> None:
        """Switch the bot on or off; the default bot carries sign-in and stays on."""
        if self.is_default and not enabled:
            raise BotDefaultLockedError(support_details=f"bot {self.id}")
        self.enabled = enabled

    def set_features(self, changes: dict[BotFeature, bool]) -> None:
        """Apply some switches; the rest keep their value."""
        self.features = {**self.features, **changes}

    def rename(self, name: str) -> None:
        """Change the display name."""
        self.name = check_name(name)

    def rotate(self, identity: BotIdentity, hint: str) -> None:
        """Accept a new token of the same Telegram bot."""
        if identity.telegram_id != self.telegram_id:
            raise BotTokenMismatchError(support_details=f"bot {self.id}")
        self.username = identity.username
        self.token_hint = hint

    def snapshot(self) -> "TelegramBot":
        """A copy for caches (callers never mutate the registry's entity)."""
        return replace(self, features=dict(self.features))
