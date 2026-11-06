"""Sharing a file: grants and link tokens (FILE-SHARE); no framework, no I/O."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

MAX_FILE_SHARES: Final = 50
TOKEN_BYTES: Final = 32


class FileShareVia(StrEnum):
    """How a person got access; turning a link off removes only ``link`` grants."""

    DIRECT = "direct"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class FileShare:
    """A person's access to a file; ``revoked_at`` keeps them out of the link."""

    file_id: UUID
    user_id: UUID
    via: FileShareVia
    created_at: datetime
    revoked_at: datetime | None = None


def new_token() -> str:
    """A new unguessable link token (shown once, only its hash is stored)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The stored form of a link token."""
    return hashlib.sha256(token.encode()).hexdigest()
