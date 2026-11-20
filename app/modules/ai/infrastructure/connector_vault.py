"""Connector keys in Vault KV v2 (`<kv_prefix>/<connector_id>`, own AppRole).

Off by default (`AI_CONNECTOR_VAULT__ENABLED`): `DisabledConnectorSecrets` refuses to
store a key, and only the connectors made from the environment work.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from app.modules.ai.domain.errors import ConnectorSecretUnavailableError
from app.settings import AiConnectorVaultSettings

import hvac
from hvac.exceptions import InvalidPath, VaultError

_RENEW_MARGIN_SECONDS = 60
_TIMEOUT_SECONDS = 15
T = TypeVar("T")


class DisabledConnectorSecrets:
    """Implements `ConnectorSecrets` when Vault is not set up for connectors."""

    async def get(self, connector_id: str) -> Mapping[str, Any] | None:
        """No key is stored."""
        return None

    async def put(self, connector_id: str, secret: Mapping[str, Any]) -> None:
        """A key cannot be saved."""
        raise ConnectorSecretUnavailableError(
            support_details="ai connector vault is disabled"
        )

    async def delete(self, connector_id: str) -> None:
        """Nothing to delete."""


class VaultConnectorSecrets:
    """Implements `ConnectorSecrets`; hvac blocks, so each call runs in a thread."""

    def __init__(self, settings: AiConnectorVaultSettings) -> None:
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
            role_id, secret_id = self._settings.role_id, self._settings.secret_id
            if role_id is None or secret_id is None:
                raise ConnectorSecretUnavailableError(support_details="no approle")
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
            except (VaultError, OSError, KeyError, ValueError) as exc:
                raise ConnectorSecretUnavailableError(
                    support_details=f"vault: {type(exc).__name__}"
                ) from exc

        return await asyncio.to_thread(guarded)

    def _path(self, connector_id: str) -> str:
        return f"{self._settings.kv_prefix}/{connector_id}"

    async def get(self, connector_id: str) -> Mapping[str, Any] | None:
        """The latest version of the secret, or None."""

        def call() -> Mapping[str, Any] | None:
            try:
                response = self._client.secrets.kv.v2.read_secret_version(
                    path=self._path(connector_id),
                    mount_point=self._settings.kv_mount,
                    raise_on_deleted_version=True,
                )
            except InvalidPath:
                return None
            data: dict[str, Any] = response["data"]["data"]
            return data

        return await self._run(call)

    async def put(self, connector_id: str, secret: Mapping[str, Any]) -> None:
        """Write the secret; an existing one gets a new version."""
        await self._run(
            lambda: self._client.secrets.kv.v2.create_or_update_secret(
                path=self._path(connector_id),
                secret=dict(secret),
                mount_point=self._settings.kv_mount,
            )
        )

    async def delete(self, connector_id: str) -> None:
        """Delete the secret and all its versions; a missing one is fine."""

        def call() -> None:
            try:
                self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=self._path(connector_id), mount_point=self._settings.kv_mount
                )
            except InvalidPath:
                return

        await self._run(call)
