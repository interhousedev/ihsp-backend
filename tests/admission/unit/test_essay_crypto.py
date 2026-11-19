"""The per-student essay cipher: AES-256-GCM blobs, key cache, Vault key store."""

import asyncio
import base64
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.errors import EssayVaultUnavailableError
from app.modules.admission.infrastructure.essay_crypto import (
    NONCE_BYTES,
    VERSION_AES_GCM_SIV,
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
    RefusingEssayKeyStore,
    VaultEssayKeyStore,
    essay_cipher,
)
from app.modules.admission.ports.essay_crypto import EssayKey
from app.settings import EssayVaultSettings, Settings

import pytest
from hvac.exceptions import InvalidPath, InvalidRequest
from pydantic import SecretStr

OWNER = UUID("00000000-0000-0000-0000-0000000000a1")
OTHER = UUID("00000000-0000-0000-0000-0000000000b1")
RECORD = UUID("00000000-0000-0000-0000-0000000000c1")
RECORD_2 = UUID("00000000-0000-0000-0000-0000000000c2")


class CountingStore(MemoryEssayKeyStore):
    """A memory store that counts calls and yields to the loop on each one."""

    def __init__(self) -> None:
        """Start with zero calls."""
        super().__init__()
        self.gets = 0
        self.creates = 0

    async def get(self, owner_id: UUID) -> EssayKey | None:
        """Count, yield, then read."""
        self.gets += 1
        await asyncio.sleep(0)
        return await super().get(owner_id)

    async def create(self, owner_id: UUID) -> EssayKey:
        """Count, yield, then create."""
        self.creates += 1
        await asyncio.sleep(0)
        return await super().create(owner_id)


class Ticker:
    """A settable monotonic clock."""

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0

    def __call__(self) -> float:
        """Return the current time."""
        return self.now


@pytest.mark.parametrize("text", ["An essay.", "", "Ўзбек ʻoʼ тест 😀", '{"a": [1]}'])
async def test_round_trip(text: str) -> None:
    """ADM-CRYPT-1: seal then open returns the text; the blob hides it."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    blob = await cipher.seal(OWNER, RECORD, "body", text)
    assert text.encode() not in blob or text == ""
    assert await cipher.open(OWNER, RECORD, "body", blob) == text


@pytest.mark.parametrize(
    ("owner", "record", "column"),
    [(OTHER, RECORD, "body"), (OWNER, RECORD_2, "body"), (OWNER, RECORD, "title")],
)
async def test_associated_data_binds_owner_record_column(
    owner: UUID, record: UUID, column: str
) -> None:
    """ADM-CRYPT-2: a blob moved to another owner, row or column does not open."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    await cipher.seal(OTHER, RECORD, "body", "x")  # the other owner has a key too
    blob = await cipher.seal(OWNER, RECORD, "body", "secret")
    with pytest.raises(ValueError):
        await cipher.open(owner, record, column, blob)


async def test_tampered_truncated_and_unknown_version_fail() -> None:
    """ADM-CRYPT-3: a flipped bit, a short blob and version 0x02 raise ValueError."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    blob = await cipher.seal(OWNER, RECORD, "body", "secret")
    flipped = blob[:-1] + bytes([blob[-1] ^ 1])
    for bad in (
        flipped,
        blob[: 1 + NONCE_BYTES + 15],
        bytes([VERSION_AES_GCM_SIV]) + blob[1:],
    ):
        with pytest.raises(ValueError):
            await cipher.open(OWNER, RECORD, "body", bad)


async def test_nonces_are_unique() -> None:
    """ADM-CRYPT-4: 1000 seals of the same text use 1000 different nonces."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    blobs = [await cipher.seal(OWNER, RECORD, "body", "same") for _ in range(1000)]
    assert len({b[1 : 1 + NONCE_BYTES] for b in blobs}) == 1000


async def test_concurrent_seals_load_the_key_once() -> None:
    """ADM-CRYPT-5: 50 concurrent first seals cause one get and one create."""
    store = CountingStore()
    cipher = AesGcmEssayCipher(store)
    blobs = await asyncio.gather(
        *(cipher.seal(OWNER, RECORD, "body", str(i)) for i in range(50))
    )
    assert (store.gets, store.creates) == (1, 1)
    assert await cipher.open(OWNER, RECORD, "body", blobs[7]) == "7"


async def test_cache_ttl() -> None:
    """ADM-CRYPT-6: the key is reused before 300 s and reloaded after."""
    store, clock = CountingStore(), Ticker()
    cipher = AesGcmEssayCipher(store, clock=clock)
    blob = await cipher.seal(OWNER, RECORD, "body", "x")
    clock.now = 299.0
    await cipher.open(OWNER, RECORD, "body", blob)
    assert store.gets == 1
    clock.now = 301.0
    await cipher.open(OWNER, RECORD, "body", blob)
    assert store.gets == 2


async def test_cache_evicts_least_recently_used() -> None:
    """ADM-CRYPT-7: with room for one key, a second owner evicts the first."""
    store = CountingStore()
    cipher = AesGcmEssayCipher(store, cache_size=1)
    blob = await cipher.seal(OWNER, RECORD, "body", "x")
    await cipher.seal(OTHER, RECORD, "body", "y")
    await cipher.open(OWNER, RECORD, "body", blob)
    assert store.gets == 3


async def test_forget_shreds_the_key() -> None:
    """ADM-CRYPT-8: after forget the old blob never opens again."""
    store = MemoryEssayKeyStore()
    cipher = AesGcmEssayCipher(store)
    blob = await cipher.seal(OWNER, RECORD, "body", "secret")
    await cipher.forget(OWNER)
    assert OWNER not in store.keys
    with pytest.raises(ValueError):
        await cipher.open(OWNER, RECORD, "body", blob)


async def test_digest() -> None:
    """ADM-CRYPT-9: 64 hex, deterministic, separated by purpose and by owner."""
    cipher = AesGcmEssayCipher(MemoryEssayKeyStore())
    first = await cipher.digest(OWNER, "dedupe", "text")
    assert len(first) == 64 and int(first, 16) >= 0
    assert await cipher.digest(OWNER, "dedupe", "text") == first
    assert await cipher.digest(OWNER, "other", "text") != first
    assert await cipher.digest(OTHER, "dedupe", "text") != first


async def test_refusing_store_fails_closed() -> None:
    """ADM-CRYPT-10: without a configured Vault in production every call is 503."""
    cipher = AesGcmEssayCipher(RefusingEssayKeyStore())
    with pytest.raises(EssayVaultUnavailableError):
        await cipher.seal(OWNER, RECORD, "body", "x")


class FakeKv:
    """hvac's kv.v2 with one pre-existing secret written by another process."""

    def __init__(self, winner: dict[str, Any] | None) -> None:
        """Hold the stored secret, if any."""
        self.winner = winner

    def read_secret_version(self, **_: Any) -> dict[str, Any]:
        """Return the stored secret or raise InvalidPath."""
        if self.winner is None:
            raise InvalidPath()
        return {"data": {"data": self.winner}}

    def create_or_update_secret(self, **kwargs: Any) -> None:
        """Refuse when the secret exists (cas=0)."""
        assert kwargs["cas"] == 0
        if self.winner is not None:
            raise InvalidRequest()
        self.winner = kwargs["secret"]


def _vault(kv: FakeKv) -> VaultEssayKeyStore:
    store = VaultEssayKeyStore(
        EssayVaultSettings(url="http://vault.invalid", token=SecretStr("t"))
    )
    cast(Any, store)._client = SimpleNamespace(
        secrets=SimpleNamespace(kv=SimpleNamespace(v2=kv))
    )
    return store


async def test_vault_create_race_returns_the_winner() -> None:
    """ADM-CRYPT-11: a lost check-and-set reads back the other process's key."""
    secret = bytes(range(32))
    store = _vault(FakeKv({"dek": base64.b64encode(secret).decode()}))
    key = await store.create(OWNER)
    assert key.secret == secret


async def test_vault_create_and_missing_key() -> None:
    """ADM-CRYPT-12: a missing key reads as None; create stores dek and alg."""
    kv = FakeKv(None)
    store = _vault(kv)
    assert await store.get(OWNER) is None
    key = await store.create(OWNER)
    assert kv.winner is not None and kv.winner["alg"] == "A256GCM"
    assert (await store.get(OWNER)) == key


def _settings(env: str, token: str | None) -> Settings:
    vault = EssayVaultSettings(token=SecretStr(token) if token else None)
    return cast(Settings, SimpleNamespace(env=env, essay_vault=vault))


@pytest.mark.parametrize(
    ("env", "token", "store"),
    [
        ("prod", "t", VaultEssayKeyStore),
        ("prod", None, RefusingEssayKeyStore),
        ("dev", None, MemoryEssayKeyStore),
    ],
)
def test_essay_cipher_selection(env: str, token: str | None, store: type) -> None:
    """ADM-CRYPT-13: Vault when configured, refusal in prod, memory in dev."""
    cipher = essay_cipher(_settings(env, token))
    assert isinstance(cast(Any, cipher)._store, store)
