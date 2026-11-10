"""Device tokens: 256 random bits behind a fixed prefix; only the hash is stored."""

import hashlib
import secrets
from dataclasses import dataclass

TOKEN_PREFIX = "ihsp_dev_"
SHOWN_CHARS = 8  # characters of the secret part kept as the visible key prefix


@dataclass(frozen=True, slots=True)
class NewToken:
    """A freshly minted token: shown once, never stored."""

    token: str
    key_prefix: str
    key_hash: str


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest the database stores."""
    return hashlib.sha256(token.encode()).hexdigest()


def mint_token() -> NewToken:
    """Create a token with 256 bits of randomness."""
    secret = secrets.token_hex(32)
    token = TOKEN_PREFIX + secret
    return NewToken(
        token=token,
        key_prefix=TOKEN_PREFIX + secret[:SHOWN_CHARS],
        key_hash=hash_token(token),
    )


def looks_like_token(value: str) -> bool:
    """Return True when the value has the device token shape."""
    return value.startswith(TOKEN_PREFIX) and len(value) == len(TOKEN_PREFIX) + 64
