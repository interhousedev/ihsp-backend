"""Authors and tags of the catalogue: names as typed, matched by a loose key (LIB-2)."""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.modules.library.domain.name_keys import (
    NAME_MAX,
    TAG_MAX,
    clean_label,
    name_key,
)

MAX_TAGS = 20
AUTHOR_SUGGESTIONS = 8


@dataclass(slots=True)
class Author:
    """A person who wrote a book; `name_key` is the same for every spelling."""

    id: UUID
    name: str
    name_key: str


@dataclass(slots=True)
class Tag:
    """A free label a librarian or a student puts on an item."""

    id: UUID
    name: str
    name_key: str


@dataclass(frozen=True, slots=True)
class TagCount:
    """A tag with the number of published items that carry it."""

    tag: Tag
    item_count: int


def distinct_labels(names: Iterable[str], limit: int) -> list[tuple[str, str]]:
    """`(label, key)` pairs: cleaned, non-empty, one per key, in the given order."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for raw in names:
        label = clean_label(raw, limit)
        key = name_key(label)
        if not label or not key or key in seen:
            continue
        seen.add(key)
        result.append((label, key))
    return result


def distinct_authors(names: Iterable[str]) -> list[tuple[str, str]]:
    """Authors as `(name, key)`; two spellings of one person count once."""
    return distinct_labels(names, NAME_MAX)


def distinct_tags(names: Iterable[str]) -> list[tuple[str, str]]:
    """Tags as `(name, key)`, at most `MAX_TAGS`."""
    return distinct_labels(names, TAG_MAX)[:MAX_TAGS]
