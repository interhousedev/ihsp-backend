"""Per-student envelope encryption of essay text (AES-256-GCM, keys in Vault KV v2).

Local AEAD with a cached data key costs microseconds per field, while Vault Transit
would add a network round trip to every read of every essay. XChaCha20 would need
PyNaCl, a new dependency; AES-GCM is in `cryptography` already. A random 96-bit
nonce is safe for 2^32 seals per key; a busy student makes about 2^23 a year.

Blob layout: version byte ``0x01`` | 12-byte nonce | ciphertext with the 16-byte tag.
The associated data binds ``owner_id|record_id|column``, so a blob copied to another
row, column or student fails to open. Version ``0x02`` is reserved for AES-GCM-SIV
(nonce-misuse resistant) and is rejected until it is implemented.
"""

import asyncio
import base64
import hashlib
import hmac
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, TypeVar
from uuid import UUID

from app.modules.admission.domain.errors import (
    EssayKeyUnavailableError,
    EssayVaultUnavailableError,
)
from app.modules.admission.ports.essay_crypto import (
    KEY_BYTES,
    EssayCipher,
    EssayKey,
    EssayKeyStore,
)
from app.settings import EssayVaultSettings, Settings

import hvac
import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from hvac.exceptions import InvalidPath, InvalidRequest, VaultError

log = structlog.get_logger(__name__)

VERSION_AES_GCM: Final = 0x01
"""Blob version of AES-256-GCM with a random 96-bit nonce."""
VERSION_AES_GCM_SIV: Final = 0x02
"""Reserved for AES-256-GCM-SIV; rejected today."""
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16
CACHE_SIZE: Final = 1024
"""Data keys kept in memory per process."""
CACHE_TTL_SECONDS: Final = 300.0
"""How long a cached key lives; a destroyed key may stay usable elsewhere this long."""
ALG: Final = "A256GCM"
_DIGEST_INFO: Final = b"ihsp-essay-digest|"
_RENEW_MARGIN_SECONDS: Final = 60
_TIMEOUT_SECONDS: Final = 15
T = TypeVar("T")


def _aad(owner_id: UUID, record_id: UUID, column: str) -> bytes:
    return f"{owner_id}|{record_id}|{column}".encode()


class AesGcmEssayCipher:
    """Implements `EssayCipher` over an `EssayKeyStore` with an LRU+TTL key cache."""

    def __init__(
        self,
        store: EssayKeyStore,
        *,
        clock: Callable[[], float] = time.monotonic,
        cache_size: int = CACHE_SIZE,
        ttl_seconds: float = CACHE_TTL_SECONDS,
    ) -> None:
        """Wrap the key store; the clock is monotonic seconds (injectable for tests)."""
        self._store = store
        self._clock = clock
        self._size = cache_size
        self._ttl = ttl_seconds
        self._cache: OrderedDict[UUID, tuple[EssayKey, float]] = OrderedDict()
        self._pending: dict[tuple[UUID, bool], asyncio.Future[EssayKey | None]] = {}

    def _cached(self, owner_id: UUID) -> EssayKey | None:
        hit = self._cache.get(owner_id)
        if hit is None:
            return None
        if self._clock() >= hit[1]:
            del self._cache[owner_id]
            return None
        self._cache.move_to_end(owner_id)
        return hit[0]

    def _remember(self, key: EssayKey) -> None:
        self._cache[key.owner_id] = (key, self._clock() + self._ttl)
        self._cache.move_to_end(key.owner_id)
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)

    async def _load(self, owner_id: UUID, create: bool) -> EssayKey | None:
        key = await self._store.get(owner_id)
        if key is None and create:
            key = await self._store.create(owner_id)
        if key is not None:
            self._remember(key)
        return key

    async def _key(self, owner_id: UUID, create: bool) -> EssayKey | None:
        """Return the key, loading it once for all concurrent callers."""
        cached = self._cached(owner_id)
        if cached is not None:
            return cached
        slot = (owner_id, create)
        pending = self._pending.get(slot)
        if pending is None:
            pending = asyncio.ensure_future(self._load(owner_id, create))
            self._pending[slot] = pending
            pending.add_done_callback(lambda _: self._pending.pop(slot, None))
        return await asyncio.shield(pending)

    async def _required(self, owner_id: UUID) -> EssayKey:
        key = await self._key(owner_id, create=True)
        assert key is not None  # create always returns a key
        return key

    async def seal(
        self, owner_id: UUID, record_id: UUID, column: str, text: str
    ) -> bytes:
        """Encrypt `text` under the owner's key, creating the key when missing."""
        key = await self._required(owner_id)
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(key.secret).encrypt(
            nonce, text.encode(), _aad(owner_id, record_id, column)
        )
        return bytes([VERSION_AES_GCM]) + nonce + sealed

    async def open(
        self, owner_id: UUID, record_id: UUID, column: str, blob: bytes
    ) -> str:
        """Decrypt a blob; ValueError if tampered or foreign, 503 without a key."""
        if len(blob) < 1 + NONCE_BYTES + TAG_BYTES:
            raise ValueError("essay blob too short")
        if blob[0] != VERSION_AES_GCM:
            raise ValueError("unknown essay blob version")
        key = await self._key(owner_id, create=False)
        if key is None:
            log.error("essay_key_missing", owner_id=str(owner_id))
            raise EssayKeyUnavailableError(support_details="essay key missing")
        nonce, sealed = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
        try:
            plain = AESGCM(key.secret).decrypt(
                nonce, sealed, _aad(owner_id, record_id, column)
            )
        except InvalidTag as exc:
            raise ValueError("essay blob does not open") from exc
        return plain.decode()

    async def digest(self, owner_id: UUID, purpose: str, data: str) -> str:
        """HMAC-SHA256 of `data` under an HKDF subkey of the owner's key (hex)."""
        key = await self._required(owner_id)
        subkey = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_BYTES,
            salt=None,
            info=_DIGEST_INFO + purpose.encode(),
        ).derive(key.secret)
        return hmac.new(subkey, data.encode(), hashlib.sha256).hexdigest()

    async def forget(self, owner_id: UUID) -> None:
        """Destroy the owner's key in the store and drop it from this cache."""
        self._cache.pop(owner_id, None)
        await self._store.destroy(owner_id)
        self._cache.pop(owner_id, None)


class MemoryEssayKeyStore:
    """Keys in process memory; tests and development without Vault only."""

    def __init__(self) -> None:
        """Start with no keys."""
        self.keys: dict[UUID, EssayKey] = {}

    async def get(self, owner_id: UUID) -> EssayKey | None:
        """Return the key or None."""
        return self.keys.get(owner_id)

    async def create(self, owner_id: UUID) -> EssayKey:
        """Create the key once; return the existing one when it is already there."""
        return self.keys.setdefault(owner_id, EssayKey(owner_id, os.urandom(KEY_BYTES)))

    async def destroy(self, owner_id: UUID) -> None:
        """Delete the key."""
        self.keys.pop(owner_id, None)


class RefusingEssayKeyStore:
    """Production without Vault settings: every call fails closed (503)."""

    async def get(self, owner_id: UUID) -> EssayKey | None:
        """Refuse."""
        raise EssayVaultUnavailableError(support_details="essay vault not configured")

    async def create(self, owner_id: UUID) -> EssayKey:
        """Refuse."""
        raise EssayVaultUnavailableError(support_details="essay vault not configured")

    async def destroy(self, owner_id: UUID) -> None:
        """Refuse."""
        raise EssayVaultUnavailableError(support_details="essay vault not configured")


class VaultEssayKeyStore:
    """Data keys in Vault KV v2 (``<prefix>/<student id>``); hvac runs in a thread."""

    def __init__(self, settings: EssayVaultSettings) -> None:
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
                # Only the exception type goes out, never a token or a key.
                raise EssayVaultUnavailableError(
                    support_details=f"vault: {type(exc).__name__}"
                ) from exc

        return await asyncio.to_thread(guarded)

    def _path(self, owner_id: UUID) -> str:
        return f"{self._settings.kv_prefix}/{owner_id}"

    def _read(self, owner_id: UUID) -> EssayKey | None:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=self._path(owner_id),
                mount_point=self._settings.kv_mount,
                raise_on_deleted_version=True,
            )
        except InvalidPath:
            return None
        return EssayKey(owner_id, base64.b64decode(response["data"]["data"]["dek"]))

    async def get(self, owner_id: UUID) -> EssayKey | None:
        """The student's key, or None when it does not exist."""
        return await self._run(lambda: self._read(owner_id))

    async def create(self, owner_id: UUID) -> EssayKey:
        """Write a new key with cas=0; after a lost race read back the winner."""
        fresh = EssayKey(owner_id, os.urandom(KEY_BYTES))
        secret = {
            "dek": base64.b64encode(fresh.secret).decode(),
            "alg": ALG,
            "created_at": datetime.now(UTC).isoformat(),
        }

        def call() -> EssayKey:
            try:
                self._client.secrets.kv.v2.create_or_update_secret(
                    path=self._path(owner_id),
                    secret=secret,
                    cas=0,
                    mount_point=self._settings.kv_mount,
                )
            except InvalidRequest:
                winner = self._read(owner_id)  # check-and-set lost: someone made it
                if winner is None:
                    raise
                return winner
            return fresh

        return await self._run(call)

    async def destroy(self, owner_id: UUID) -> None:
        """Delete the key's metadata and every version (crypto-shredding)."""

        def call() -> None:
            try:
                self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=self._path(owner_id), mount_point=self._settings.kv_mount
                )
            except InvalidPath:
                return

        await self._run(call)


def _vault_configured(settings: EssayVaultSettings) -> bool:
    return bool((settings.role_id and settings.secret_id) or settings.token)


def essay_cipher(settings: Settings) -> EssayCipher:
    """The process's essay cipher: Vault when configured, never plaintext.

    Production without Vault settings refuses every essay operation (503);
    development without Vault keeps keys in memory, so essays die with the process.
    """
    if _vault_configured(settings.essay_vault):
        return AesGcmEssayCipher(VaultEssayKeyStore(settings.essay_vault))
    if settings.env == "prod":
        log.error("essay_vault_not_configured")
        return AesGcmEssayCipher(RefusingEssayKeyStore())
    log.warning("essay_keys_in_memory")
    return AesGcmEssayCipher(MemoryEssayKeyStore())


__all__ = [
    "AesGcmEssayCipher",
    "MemoryEssayKeyStore",
    "RefusingEssayKeyStore",
    "VaultEssayKeyStore",
    "essay_cipher",
]
