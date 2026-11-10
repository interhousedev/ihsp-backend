"""Schemas of the Vault unseal endpoints."""

from app.modules.identity.ports.vault_seal import VaultSealStatus

from pydantic import BaseModel, SecretStr


class VaultStatusResponse(BaseModel):
    """Seal state."""

    sealed: bool
    progress: int
    threshold: int
    shares: int

    @classmethod
    def of(cls, status: VaultSealStatus) -> "VaultStatusResponse":
        """Map the port's state."""
        return cls(
            sealed=status.sealed,
            progress=status.progress,
            threshold=status.threshold,
            shares=status.shares,
        )


class VaultUnsealBody(BaseModel):
    """POST /v1/admin/vault/unseal; the key is never echoed or logged."""

    key: SecretStr
    otp_code: str | None = None
