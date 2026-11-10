"""Personal API token entity and token format."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.shared.ids import hash_token, random_token

TOKEN_PREFIX = "ihsp_pat_"
PREFIX_LENGTH = 8
ALLOWED_EXPIRY_DAYS = (30, 90, 365)
MAX_NAME_LENGTH = 80


class PersonalTokenScope(StrEnum):
    """What a personal token may do under /v1/me/*."""

    ME_READ = "me:read"
    ME_WRITE = "me:write"


@dataclass(slots=True)
class PersonalToken:
    """A long-lived API token of one user, stored as a hash."""

    id: UUID
    user_id: UUID
    name: str
    prefix: str
    token_hash: str
    scopes: list[str]
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = field(default=None)

    def is_active(self, now: datetime) -> bool:
        """True while not revoked and not expired."""
        return self.revoked_at is None and self.expires_at > now


def new_token() -> tuple[str, str, str]:
    """Return (token, sha256 hash, display prefix) for a fresh personal token."""
    secret = random_token(32)
    token = TOKEN_PREFIX + secret
    return token, hash_token(token), secret[:PREFIX_LENGTH]


def looks_like_token(value: str) -> bool:
    """Cheap format check before hitting the database."""
    return value.startswith(TOKEN_PREFIX) and len(value) > len(TOKEN_PREFIX)
