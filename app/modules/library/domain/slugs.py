"""Slugs of items: a readable stem plus eight hex characters of the item id."""

from uuid import UUID

from app.shared.text import slugify

STEM_MAX = 80


def make_slug(title: str, item_id: UUID) -> str:
    """`physics-10-grade-1a2b3c4d`: unique because the id tail is random (UUIDv7)."""
    stem = slugify(title)[:STEM_MAX].strip("-") or "item"
    return f"{stem}-{item_id.hex[-8:]}"
