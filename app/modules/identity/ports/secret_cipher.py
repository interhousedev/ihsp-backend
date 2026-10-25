"""Port: encryption of small secrets (Vault Transit in production)."""

from typing import Protocol


class SecretCipher(Protocol):
    """Encrypts and decrypts strings; the key never leaves Vault."""

    async def encrypt(self, plaintext: str) -> str:
        """Return the ciphertext."""
        ...

    async def decrypt(self, ciphertext: str) -> str:
        """Return the plaintext."""
        ...
