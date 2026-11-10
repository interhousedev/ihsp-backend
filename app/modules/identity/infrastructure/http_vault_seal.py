"""Vault seal client over plain HTTP (no token needed while sealed)."""

from typing import Any

from app.modules.identity.domain.errors import (
    VaultKeyRejectedError,
    VaultUnavailableError,
)
from app.modules.identity.ports.vault_seal import VaultSealStatus
from app.settings import VaultSettings

import httpx
from pydantic import SecretStr

TIMEOUT_SECONDS = 10.0


def _parse(data: Any) -> VaultSealStatus:
    try:
        return VaultSealStatus(
            sealed=bool(data["sealed"]),
            progress=int(data.get("progress", 0)),
            threshold=int(data.get("t", 0)),
            shares=int(data.get("n", 0)),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise VaultUnavailableError(
            support_details="vault: unexpected answer"
        ) from None


class HttpVaultSeal:
    """VaultSeal: /v1/sys/seal-status and /v1/sys/unseal."""

    def __init__(self, settings: VaultSettings) -> None:
        """Keep the address and the TLS setting."""
        self._url = settings.url.rstrip("/")
        self._verify = settings.verify

    async def status(self) -> VaultSealStatus:
        """Return the seal state."""
        return _parse(await self._call("GET", "/v1/sys/seal-status"))

    async def submit_key(self, key: SecretStr) -> VaultSealStatus:
        """Submit one key share; the share only travels in the request body."""
        body = {"key": key.get_secret_value()}
        return _parse(await self._call("PUT", "/v1/sys/unseal", body))

    async def _call(
        self, method: str, path: str, body: dict[str, str] | None = None
    ) -> Any:
        # `from None`: an exception chain must never carry the request body.
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, verify=self._verify
            ) as client:
                response = await client.request(method, self._url + path, json=body)
        except httpx.HTTPError as exc:
            raise VaultUnavailableError(
                support_details=f"vault: {type(exc).__name__}"
            ) from None
        if response.status_code == 400 and body is not None:
            raise VaultKeyRejectedError()
        if response.status_code >= 300:
            raise VaultUnavailableError(
                support_details=f"vault: HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError:
            raise VaultUnavailableError(support_details="vault: not JSON") from None
