"""A sealed Vault is reported as its own error, not as a generic Vault failure."""

from types import SimpleNamespace
from typing import Any

from app.modules.identity.application.register_models import CredentialStoreError
from app.modules.identity.domain.errors import VaultSealedError
from app.modules.identity.infrastructure.vault.client import VaultCredentialStore
from app.settings import VaultSettings

import pytest
from hvac.exceptions import VaultDown


def store_failing_with(message: str) -> VaultCredentialStore:
    """A store whose Transit decrypt raises VaultDown(message)."""
    store = VaultCredentialStore(VaultSettings(url="http://vault:8200"))

    def decrypt_data(**_: Any) -> None:
        raise VaultDown(message)

    transit = SimpleNamespace(decrypt_data=decrypt_data)
    store._client = SimpleNamespace(  # type: ignore[assignment]
        secrets=SimpleNamespace(transit=transit)
    )
    return store


async def test_sealed_vault_raises_the_sealed_error() -> None:
    """Admins with the authenticator app are told to unseal, not 'try later'."""
    with pytest.raises(VaultSealedError) as caught:
        await store_failing_with("Vault is sealed").decrypt("vault:v1:x")

    assert caught.value.code == "id/vault-sealed"
    assert caught.value.status == 503


async def test_other_vault_downtime_stays_a_store_error() -> None:
    """Only the sealed state gets the dedicated error."""
    with pytest.raises(CredentialStoreError):
        await store_failing_with("Vault is in standby").decrypt("vault:v1:x")
