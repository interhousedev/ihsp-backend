"""Identifiers, tokens and codes."""

import base64
import hashlib
import secrets
from uuid import UUID

import uuid_utils

SHORT_ID_ALPHABET = "123456789ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz-_~"
SHORT_ID_PREFERRED = "123456789-_~"


def new_id() -> UUID:
    """Return a new UUIDv7 as a stdlib UUID."""
    return UUID(str(uuid_utils.uuid7()))


def random_token(nbytes: int = 32) -> str:
    """Return a URL-safe random token (256 bits by default)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest used to store tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def random_digits(length: int) -> str:
    """Return a random numeric code, e.g. an OTP or a room PIN."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def uuid_to_b64(value: UUID) -> str:
    """Pack a UUID into 22 URL-safe characters (for Telegram callback data)."""
    return base64.urlsafe_b64encode(value.bytes).rstrip(b"=").decode()


def b64_to_uuid(value: str) -> UUID:
    """Unpack uuid_to_b64."""
    return UUID(bytes=base64.urlsafe_b64decode(value + "=="))
