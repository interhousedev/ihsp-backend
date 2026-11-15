"""The default bot's token for the processes that only use that bot.

``TELEGRAM__BOT_TOKEN`` wins when set (the behaviour before the registry). Without
it the default bot of the registry runs on its Vault token, so the env lines can
be removed once the token lives in Vault (``python -m app import-default-bot``).
"""

from uuid import UUID

from app.modules.admin.domain.errors import BotVaultUnavailableError
from app.modules.admin.domain.telegram_bot import TelegramBot
from app.modules.admin.infrastructure.bot_registry import BotRegistryCache
from app.modules.admin.ports.telegram_bots import BotTokenVault

import structlog

log = structlog.get_logger(__name__)


class DefaultBotToken:
    """Resolves the default bot and its token; the registry reloads every 30 s.

    The Vault token is read again when the bot row changes (``updated_at``, bumped
    by a rotation); while Vault is unreachable the last good token is kept.
    """

    def __init__(
        self,
        env_token: str | None,
        *,
        registry: BotRegistryCache,
        vault: BotTokenVault,
    ) -> None:
        """An empty ``env_token`` means the registry's default bot."""
        self._env_token = env_token or None
        self._registry = registry
        self._vault = vault
        self._cached: tuple[UUID, str, str] | None = None  # id, version, token

    @property
    def from_env(self) -> bool:
        """Whether the env token is used."""
        return self._env_token is not None

    async def bot(self) -> TelegramBot | None:
        """The registry's default bot."""
        return next((bot for bot in await self._registry.all() if bot.is_default), None)

    async def get(self) -> str | None:
        """The token, or None when there is no default bot or no readable token."""
        if self._env_token is not None:
            return self._env_token
        bot = await self.bot()
        if bot is None:
            return None
        version = bot.updated_at.isoformat()
        cached = self._cached
        if cached is not None and cached[0] == bot.id and cached[1] == version:
            return cached[2]
        try:
            token = await self._vault.get(bot.id)
        except BotVaultUnavailableError:
            log.warning("default_bot_token_unavailable", bot_id=str(bot.id))
            return cached[2] if cached is not None and cached[0] == bot.id else None
        if token is None:
            return None
        self._cached = (bot.id, version, token)
        return token
