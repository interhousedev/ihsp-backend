"""A revocable link to the media of a live step, issued to an enrolled student."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

ANONYMOUS_WINDOW: Final = timedelta(hours=5)

MediaTier = Literal["anon", "enrolled", "denied"]


@dataclass(frozen=True, slots=True)
class MediaGrant:
    """One active link per user, step and block; only the token's hash is stored."""

    id: UUID
    course_id: UUID
    step_id: UUID
    block_id: str
    file_id: UUID
    issued_to: UUID
    connector_id: UUID | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    redeem_count: int


def new_token() -> str:
    """Return an opaque 256-bit token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return the stored form of a token."""
    return hashlib.sha256(token.encode()).hexdigest()
