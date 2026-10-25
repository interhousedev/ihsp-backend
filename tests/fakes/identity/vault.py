"""In-memory stand-in for Vault (CredentialStore) that records what happened."""

import base64
from uuid import UUID

from app.modules.identity.application.register_models import (
    CredentialNotFoundError,
    CredentialStoreError,
    EmisSecret,
)


class InMemoryCredentialStore:
    """Transit is base64 with a prefix; KV is a dict. ``down`` simulates an outage."""

    def __init__(self) -> None:
        """Start empty and healthy."""
        self.secrets: dict[UUID, EmisSecret] = {}
        self.updated_tokens: list[tuple[UUID, str]] = []
        self.replaced: list[UUID] = []
        self.destroyed: list[UUID] = []
        self.calls: list[str] = []
        self.down = False

    def _guard(self, name: str) -> None:
        self.calls.append(name)
        if self.down:
            raise CredentialStoreError("vault is down")

    async def encrypt(self, plaintext: str) -> str:
        """Return a fake Transit ciphertext."""
        self._guard("encrypt")
        return "vault:v1:" + base64.b64encode(plaintext.encode()).decode()

    async def decrypt(self, ciphertext: str) -> str:
        """Reverse ``encrypt``."""
        self._guard("decrypt")
        raw = ciphertext.removeprefix("vault:v1:")
        return base64.b64decode(raw).decode()

    async def write(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        """Store the secret."""
        self._guard("write")
        self.secrets[ref] = EmisSecret(login, password_enc, access_token)

    async def replace(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        """Store the secret and remember that history was dropped."""
        self._guard("replace")
        self.replaced.append(ref)
        self.secrets[ref] = EmisSecret(login, password_enc, access_token)

    async def read(self, ref: UUID) -> EmisSecret:
        """Return the secret or raise CredentialNotFoundError."""
        self._guard("read")
        if ref not in self.secrets:
            raise CredentialNotFoundError(str(ref))
        return self.secrets[ref]

    async def update_token(self, ref: UUID, token: str) -> None:
        """Store a fresh token."""
        self._guard("update_token")
        secret = await self.read(ref)
        self.secrets[ref] = EmisSecret(secret.login, secret.password_enc, token)
        self.updated_tokens.append((ref, token))

    async def destroy(self, ref: UUID) -> None:
        """Forget the secret (idempotent)."""
        self._guard("destroy")
        self.secrets.pop(ref, None)
        self.destroyed.append(ref)
