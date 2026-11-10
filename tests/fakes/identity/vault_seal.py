"""In-memory VaultSeal."""

from app.modules.identity.ports.vault_seal import VaultSealStatus

from pydantic import SecretStr


class FakeVaultSeal:
    """Seals after `threshold` shares; can fail on demand."""

    def __init__(self, *, threshold: int = 3, shares: int = 5) -> None:
        """Start sealed with no progress."""
        self.threshold = threshold
        self.shares = shares
        self.progress = 0
        self.received: list[str] = []
        self.error: Exception | None = None

    def _state(self) -> VaultSealStatus:
        return VaultSealStatus(
            sealed=self.progress < self.threshold,
            progress=self.progress,
            threshold=self.threshold,
            shares=self.shares,
        )

    async def status(self) -> VaultSealStatus:
        """Return the state."""
        if self.error:
            raise self.error
        return self._state()

    async def submit_key(self, key: SecretStr) -> VaultSealStatus:
        """Count one share."""
        if self.error:
            raise self.error
        self.received.append(key.get_secret_value())
        self.progress += 1
        return self._state()
