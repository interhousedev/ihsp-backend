"""Telegram bot tokens in Vault KV v2, one secret per bot (``<prefix>/<bot id>``).

Uses its own AppRole (``IHSP_BOT_VAULT__*``, policy ``telegram-bots``), so the
api, bot and worker processes never hold the identity role that reads EMIS secrets.
"""

import asyncio
import threading
import time
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from app.modules.admin.domain.errors import BotVaultUnavailableError
from app.settings import BotVaultSettings

import hvac
from hvac.exceptions import InvalidPath, VaultError

_RENEW_MARGIN_SECONDS = 60
_TIMEOUT_SECONDS = 15
T = TypeVar("T")


class VaultBotTokenStore:
    """Implements `BotTokenVault`; hvac is blocking, so calls run in a thread."""

    def __init__(self, settings: BotVaultSettings) -> None:
        """Create the client; nothing is sent until the first call."""
        self._settings = settings
        token = settings.token.get_secret_value() if settings.token else None
        self._use_approle = bool(settings.role_id and settings.secret_id)
        self._client = hvac.Client(
            url=settings.url,
            token=None if self._use_approle else token,
            verify=settings.verify,
            timeout=_TIMEOUT_SECONDS,
        )
        self._lock = threading.Lock()
        self._expires_at = 0.0

    def _ensure_auth(self) -> None:
        if not self._use_approle:
            return
        with self._lock:
            if time.monotonic() < self._expires_at - _RENEW_MARGIN_SECONDS:
                return
            try:
                renewed = self._client.auth.token.renew_self()["auth"]
                self._expires_at = time.monotonic() + renewed["lease_duration"]
            except (VaultError, OSError, KeyError):
                role_id, secret_id = self._settings.role_id, self._settings.secret_id
                assert role_id is not None and secret_id is not None
                auth = self._client.auth.approle.login(
                    role_id=role_id, secret_id=secret_id.get_secret_value()
                )["auth"]
                self._client.token = auth["client_token"]
                self._expires_at = time.monotonic() + auth["lease_duration"]

    async def _run(self, call: Callable[[], T]) -> T:
        def guarded() -> T:
            try:
                self._ensure_auth()
                return call()
            except InvalidPath:
                raise
            except (VaultError, OSError, KeyError, ValueError) as exc:
                # Never include the token: only the exception type goes out.
                raise BotVaultUnavailableError(
                    support_details=f"vault: {type(exc).__name__}"
                ) from exc

        return await asyncio.to_thread(guarded)

    def _path(self, bot_id: UUID) -> str:
        return f"{self._settings.kv_prefix}/{bot_id}"

    async def put(self, bot_id: UUID, token: str) -> None:
        """Store the token as a new version of the bot's secret."""
        await self._run(
            lambda: self._client.secrets.kv.v2.create_or_update_secret(
                path=self._path(bot_id),
                secret={"token": token},
                mount_point=self._settings.kv_mount,
            )
        )

    async def get(self, bot_id: UUID) -> str | None:
        """The latest token, or None when the secret does not exist."""

        def call() -> str | None:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=self._path(bot_id),
                mount_point=self._settings.kv_mount,
                raise_on_deleted_version=True,
            )
            value = response["data"]["data"].get("token")
            return str(value) if value else None

        try:
            return await self._run(call)
        except InvalidPath:
            return None
