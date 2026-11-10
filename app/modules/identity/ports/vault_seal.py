"""Port: seal state of the Vault server."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class VaultSealStatus:
    """Seal state as Vault reports it."""

    sealed: bool
    progress: int
    threshold: int
    shares: int


class VaultSeal(Protocol):
    """Reads the seal state and submits unseal key shares (works while sealed)."""

    async def status(self) -> VaultSealStatus:
        """Return the seal state."""
        ...

    async def submit_key(self, key: SecretStr) -> VaultSealStatus:
        """Submit one key share and return the new state."""
        ...
