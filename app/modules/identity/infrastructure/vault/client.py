"""Vault: Transit encryption of EMIS passwords and the KV v2 secret per student."""

import asyncio
import base64
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from app.modules.identity.application.register_models import (
    CredentialNotFoundError,
    CredentialStoreError,
    EmisSecret,
)
from app.settings import VaultSettings

import hvac
from hvac.exceptions import InvalidPath, VaultError

_TRANSIT_MOUNT = "transit"
_RENEW_MARGIN_SECONDS = 60
_TIMEOUT_SECONDS = 15
T = TypeVar("T")


class VaultCredentialStore:
    """hvac is blocking, so every call runs in a worker thread."""

    def __init__(self, settings: VaultSettings) -> None:
        """Create the client; nothing is sent to Vault until the first call."""
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
        self._expires_at = 0.0  # monotonic time; AppRole tokens only

    # - - - Authentication - - -

    def _login(self) -> None:
        role_id, secret_id = self._settings.role_id, self._settings.secret_id
        if role_id is None or secret_id is None:
            raise CredentialStoreError("AppRole is not configured")
        auth = self._client.auth.approle.login(
            role_id=role_id, secret_id=secret_id.get_secret_value()
        )["auth"]
        self._client.token = auth["client_token"]
        self._expires_at = time.monotonic() + auth["lease_duration"]

    def _ensure_auth(self) -> None:
        """Log in with AppRole and renew the token early (a dev token needs neither)."""
        if not self._use_approle:
            return
        with self._lock:
            if time.monotonic() < self._expires_at - _RENEW_MARGIN_SECONDS:
                return
            try:
                renewed = self._client.auth.token.renew_self()["auth"]
                self._expires_at = time.monotonic() + renewed["lease_duration"]
            except (VaultError, OSError, KeyError):
                self._login()  # first call, or past token_max_ttl

    # - - - Plumbing - - -

    async def _run(self, call: Callable[[], T]) -> T:
        def guarded() -> T:
            try:
                self._ensure_auth()
                return call()
            except InvalidPath as exc:
                raise CredentialNotFoundError(str(exc)) from exc
            except (VaultError, OSError, KeyError, ValueError) as exc:
                # requests exceptions are OSError subclasses
                raise CredentialStoreError(f"{type(exc).__name__}: {exc}") from exc

        return await asyncio.to_thread(guarded)

    def _path(self, ref: UUID) -> str:
        return f"{self._settings.kv_prefix}/{ref}"

    # - - - Transit - - -

    async def encrypt(self, plaintext: str) -> str:
        """Encrypt with the Transit key ``VAULT__TRANSIT_KEY``."""
        encoded = base64.b64encode(plaintext.encode()).decode()

        def call() -> str:
            response = self._client.secrets.transit.encrypt_data(
                name=self._settings.transit_key,
                plaintext=encoded,
                mount_point=_TRANSIT_MOUNT,
            )
            return str(response["data"]["ciphertext"])

        return await self._run(call)

    async def decrypt(self, ciphertext: str) -> str:
        """Decrypt a Transit ciphertext."""

        def call() -> str:
            response = self._client.secrets.transit.decrypt_data(
                name=self._settings.transit_key,
                ciphertext=ciphertext,
                mount_point=_TRANSIT_MOUNT,
            )
            return base64.b64decode(response["data"]["plaintext"]).decode()

        return await self._run(call)

    # - - - KV v2 - - -

    def _write_sync(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=self._path(ref),
            secret={
                "login": login,
                "password_enc": password_enc,
                "access_token": access_token,
            },
            mount_point=self._settings.kv_mount,
        )

    def _destroy_sync(self, ref: UUID) -> None:
        try:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=self._path(ref), mount_point=self._settings.kv_mount
            )
        except InvalidPath:
            return  # nothing to destroy

    def _read_sync(self, ref: UUID) -> dict[str, Any]:
        response = self._client.secrets.kv.v2.read_secret_version(
            path=self._path(ref),
            mount_point=self._settings.kv_mount,
            raise_on_deleted_version=True,
        )
        data: dict[str, Any] = response["data"]["data"]
        return data

    async def write(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        """Write the secret; an existing secret gets a new version."""
        await self._run(
            lambda: self._write_sync(
                ref, login=login, password_enc=password_enc, access_token=access_token
            )
        )

    async def replace(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        """Write the secret after dropping every older version (old passwords)."""

        def call() -> None:
            self._destroy_sync(ref)
            self._write_sync(
                ref, login=login, password_enc=password_enc, access_token=access_token
            )

        await self._run(call)

    async def read(self, ref: UUID) -> EmisSecret:
        """Read the latest version."""
        data = await self._run(lambda: self._read_sync(ref))
        try:
            return EmisSecret(
                login=str(data["login"]),
                password_enc=str(data["password_enc"]),
                access_token=str(data["access_token"]),
            )
        except KeyError as exc:
            raise CredentialStoreError("secret is missing fields") from exc

    async def update_token(self, ref: UUID, token: str) -> None:
        """Write a new version with a fresh access token."""

        def call() -> None:
            data = self._read_sync(ref)
            self._write_sync(
                ref,
                login=str(data["login"]),
                password_enc=str(data["password_enc"]),
                access_token=token,
            )

        await self._run(call)

    async def destroy(self, ref: UUID) -> None:
        """Delete the secret and all versions (ID-9); a missing secret is fine."""
        await self._run(lambda: self._destroy_sync(ref))
