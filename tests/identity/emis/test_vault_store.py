"""ID-6, ID-9: VaultCredentialStore against the dev Vault of the compose stack."""

from collections.abc import AsyncIterator
from uuid import UUID

from app.modules.identity.application.register_models import (
    CredentialNotFoundError,
    CredentialStoreError,
)
from app.modules.identity.infrastructure.vault.client import VaultCredentialStore
from app.settings import Settings, VaultSettings
from app.shared.ids import new_id

import pytest
from pydantic import SecretStr


@pytest.fixture
async def vault(settings: Settings) -> AsyncIterator[VaultCredentialStore]:
    """The real store; the test is skipped when the dev Vault is not set up."""
    store = VaultCredentialStore(settings.vault)
    try:
        await store.encrypt("ping")
    except (CredentialStoreError, CredentialNotFoundError) as exc:
        pytest.skip(f"dev Vault with transit key is not available: {exc}")
    yield store


@pytest.fixture
async def ref(vault: VaultCredentialStore) -> AsyncIterator[UUID]:
    """A fresh secret path that is destroyed after the test."""
    value = new_id()
    yield value
    await vault.destroy(value)


async def test_transit_round_trip_keeps_unicode(vault: VaultCredentialStore) -> None:
    """ID-6: the EMIS password is encrypted with Transit."""
    ciphertext = await vault.encrypt("pässwörd-Пароль")

    assert ciphertext.startswith("vault:v1:")
    assert await vault.decrypt(ciphertext) == "pässwörd-Пароль"


async def test_a_secret_is_written_read_and_gets_a_new_token(
    vault: VaultCredentialStore, ref: UUID
) -> None:
    """ID-6: login, ciphertext and token live in KV v2."""
    await vault.write(
        ref, login="student01", password_enc="vault:v1:x", access_token="t1"
    )
    await vault.update_token(ref, "t2")

    secret = await vault.read(ref)

    assert (secret.login, secret.password_enc, secret.access_token) == (
        "student01",
        "vault:v1:x",
        "t2",
    )


async def test_destroy_removes_the_secret_and_can_repeat(
    vault: VaultCredentialStore, ref: UUID
) -> None:
    """ID-9: the secret is gone with all versions; destroying twice is fine."""
    await vault.write(ref, login="l", password_enc="p", access_token="t")

    await vault.destroy(ref)
    await vault.destroy(ref)

    with pytest.raises(CredentialNotFoundError):
        await vault.read(ref)


async def test_replace_drops_the_history_of_old_passwords(
    vault: VaultCredentialStore, ref: UUID
) -> None:
    """ID-8: after replacing, no older version of the secret stays readable."""
    await vault.write(ref, login="l", password_enc="old", access_token="t")
    await vault.update_token(ref, "t2")

    await vault.replace(ref, login="l", password_enc="new", access_token="t3")

    secret = await vault.read(ref)
    metadata = vault._client.secrets.kv.v2.read_secret_metadata(
        path=f"emis/{ref}", mount_point="secret"
    )["data"]
    assert (secret.password_enc, secret.access_token) == ("new", "t3")
    assert list(metadata["versions"]) == ["1"]


async def test_a_ciphertext_of_another_key_cannot_be_decrypted(
    vault: VaultCredentialStore,
) -> None:
    """ID-6: garbage is a store error, not a crash."""
    with pytest.raises(CredentialStoreError):
        await vault.decrypt("vault:v1:not-real-ciphertext")


async def test_an_unreachable_vault_is_a_store_error() -> None:
    """ID-7: Vault down maps to EmisUnavailable one layer up."""
    store = VaultCredentialStore(
        VaultSettings(url="http://127.0.0.1:1", token=SecretStr("x"))
    )

    with pytest.raises(CredentialStoreError):
        await store.encrypt("x")


async def test_approle_login_works(
    settings: Settings, vault: VaultCredentialStore
) -> None:
    """ID-6: production uses the AppRole ``identity`` created by the vault-init."""
    auth = vault._client.auth.approle
    try:
        role_id = auth.read_role_id("identity")["data"]["role_id"]
        secret_id = auth.generate_secret_id("identity")["data"]["secret_id"]
    except Exception as exc:  # hvac raises different errors for a missing role
        pytest.skip(f"AppRole identity is not configured: {exc}")
    approle = VaultCredentialStore(
        VaultSettings(
            url=settings.vault.url,
            token=None,
            role_id=role_id,
            secret_id=SecretStr(secret_id),
        )
    )

    ciphertext = await approle.encrypt("through-approle")

    assert await approle.decrypt(ciphertext) == "through-approle"
