"""A knowledge entry: a short fact the assistant can look up by key or meaning."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.knowledge.domain.errors import KnowledgeInvalidError

MAX_KEY = 80
MAX_TITLE = 200
MAX_VALUE = 20_000
MAX_TAGS = 20
MAX_TAG = 40
EMBED_CHARS = 8_000
"""The part of an entry that is embedded (a vector sees about this much text)."""


@dataclass(slots=True)
class KnowledgeEntry:
    """One entry; `key` is stored lower case and is unique."""

    id: UUID
    key: str
    value: str
    author_id: UUID
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    content_hash: str | None = None  # sha256 of `embed_text()` when it was embedded


@dataclass(frozen=True, slots=True)
class LexicalHit:
    """A word or trigram match: its pg_trgm similarity and ts_rank."""

    entry: KnowledgeEntry
    similarity: float
    rank: float


@dataclass(frozen=True, slots=True)
class SemanticHit:
    """A vector match with its cosine similarity (1 is the same direction)."""

    entry: KnowledgeEntry
    similarity: float


def normalize_key(raw: str) -> str:
    """Trim, collapse spaces and lower-case a key.

    Raises:
        KnowledgeInvalidError: The key is empty or longer than `MAX_KEY`.
    """
    key = " ".join(raw.split()).lower()
    if not key or len(key) > MAX_KEY:
        raise KnowledgeInvalidError(params={"field": "key"})
    return key


def normalize_title(raw: str | None) -> str | None:
    """Trim a title; empty means none."""
    title = " ".join((raw or "").split())
    if len(title) > MAX_TITLE:
        raise KnowledgeInvalidError(params={"field": "title"})
    return title or None


def normalize_value(raw: str) -> str:
    """Trim the value; it must not be empty."""
    value = raw.strip()
    if not value or len(value) > MAX_VALUE:
        raise KnowledgeInvalidError(params={"field": "value"})
    return value


def normalize_tags(raw: list[str]) -> list[str]:
    """Lower-case, trim and de-duplicate tags, keeping the order."""
    tags: list[str] = []
    for item in raw:
        tag = " ".join(item.split()).lower()
        if not tag or len(tag) > MAX_TAG:
            raise KnowledgeInvalidError(params={"field": "tags"})
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise KnowledgeInvalidError(params={"field": "tags"})
    return tags


def embed_text(entry: KnowledgeEntry) -> str:
    """The text a vector is made of: key, title and value."""
    parts = [entry.key, entry.title or "", entry.value]
    return "\n".join(part for part in parts if part)[:EMBED_CHARS]


def text_hash(text: str) -> str:
    """sha256 (hex, 64 chars) of a text as UTF-8, the key of `vectors.embeddings`."""
    return hashlib.sha256(text.encode()).hexdigest()
