"""Who sees what in a shared notebook (NB-SHARE); no framework, no I/O."""

import hashlib
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind

MAX_SHARES: Final = 50
MAX_LINKED_SETS: Final = 3
RECIPIENT_QUERY_MIN_CHARS: Final = 3
RECIPIENT_LIMIT: Final = 10
TOKEN_BYTES: Final = 32

# Material the owner wrote or that anyone may read. Chats are private, and lesson,
# course, flash card and library sources have their own audience, which a share must
# not widen: those stay out of the shared view, of copies and of attached sets.
VIEWABLE_KINDS: Final = frozenset(
    {SourceKind.FILE, SourceKind.TEXT, SourceKind.NOTE, SourceKind.URL}
    | {SourceKind.WEB_RESULT}
)


class ShareVia(StrEnum):
    """How a person got access; turning a link off removes only ``link`` grants."""

    DIRECT = "direct"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class NotebookShare:
    """A person's access to a notebook; ``revoked_at`` keeps them out of the link."""

    notebook_id: UUID
    user_id: UUID
    via: ShareVia
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LinkedSet:
    """A notebook attached to another one as a live set of sources."""

    notebook_id: UUID
    linked_notebook_id: UUID
    created_at: datetime


def is_shareable(notebook: Notebook) -> bool:
    """Only a notebook the owner writes themselves can be shared."""
    return notebook.origin is NotebookOrigin.MANUAL and not notebook.is_deleted


def viewable(sources: Iterable[Source]) -> list[Source]:
    """The sources a person other than the owner may see or send to the model."""
    return [source for source in sources if source.kind in VIEWABLE_KINDS]


def new_token() -> str:
    """A new unguessable link token (shown once, only its hash is stored)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The stored form of a link token."""
    return hashlib.sha256(token.encode()).hexdigest()
