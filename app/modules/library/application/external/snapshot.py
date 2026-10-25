"""The stored copy of a pinned UniLibrary record: facts only, never files (D3)."""

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.entities import ExternalDetails, Item
from app.modules.library.domain.enums import (
    ExternalSource,
    ItemKind,
    ItemStatus,
    Visibility,
)
from app.modules.library.domain.search_query import build_search_text
from app.modules.library.domain.slugs import make_slug
from app.modules.library.ports.external_catalog import ExternalRecord

TITLE_MAX = 255
AUTHOR_LABEL_MAX = 255
PUBLISHER_MAX = 255
ISBN_MAX = 32
ELLIPSIS = "…"


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + ELLIPSIS


def snapshot_of(record: ExternalRecord) -> dict[str, Any]:  # jsonb column
    """The facts of a record as stored in `external_details.snapshot`.

    View counts are left out: they change all the time and are not facts of the
    record, so they must not change the snapshot hash.
    """
    facts: dict[str, Any] = {
        "id": record.external_id,
        "category": record.category,
        "title": record.title,
        "authors": record.authors,
        "year": record.year,
        "publisher": record.publisher,
        "type_id": record.type_id,
        "field_id": record.field_id,
        "language_id": record.language_id,
        "access": record.access.value,
        "description": record.description,
        "cover_url": record.cover_url,
        "keywords": list(record.keywords) if record.keywords is not None else None,
        "isbn": record.isbn,
        "page_count": record.page_count,
    }
    return {key: value for key, value in facts.items() if value is not None}


def snapshot_hash(snapshot: dict[str, Any]) -> str:  # jsonb column
    """SHA-256 of the canonical (sorted, compact) JSON of the snapshot."""
    canonical = json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _names(name: str | None, locale: str) -> dict[str, str]:
    return {locale: name} if name else {}


def build_pinned_item(
    record: ExternalRecord,
    *,
    item_id: UUID,
    actor_id: UUID,
    now: datetime,
    locale: str,
) -> Item:
    """A published, lyceum-visible, link-only item for a record (doc 3.1, pin).

    No owner, no files and no cover file: the cover is the link UniLibrary gave.
    """
    snapshot = snapshot_of(record)
    authors = [part.strip() for part in record.authors.split(";") if part.strip()]
    title = _cut(record.title, TITLE_MAX)
    description = record.description
    search_extra = " ".join(record.keywords or ())
    return Item(
        id=item_id,
        slug=make_slug(record.title, item_id),
        kind=ItemKind.EXTERNAL,
        type=record.item_type,
        title=title,
        language=record.language,
        status=ItemStatus.PUBLISHED,
        visibility=Visibility.LYCEUM,
        created_at=now,
        updated_at=now,
        authors=authors,
        author_label=_cut(record.authors, AUTHOR_LABEL_MAX),
        year_published=record.year,
        publisher=_cut(record.publisher, PUBLISHER_MAX) if record.publisher else None,
        isbn=record.isbn[:ISBN_MAX] if record.isbn else None,
        description=description,
        cover_url=record.cover_url,
        page_count=record.page_count,
        search_text=build_search_text(
            language=record.language,
            title=title,
            subtitle=None,
            authors=authors,
            description=" ".join(part for part in (description, search_extra) if part),
        ),
        owner_id=None,
        created_by=actor_id,
        published_at=now,
        external=ExternalDetails(
            source=ExternalSource.UNILIBRARY,
            external_id=record.external_id,
            category=record.category,
            access=record.access,
            view_url=record.view_url,
            snapshot_hash=snapshot_hash(snapshot),
            fetched_at=now,
            detail_fetched_at=now if record.keywords is not None else None,
            type_name=_names(record.type_name, locale),
            field_name=_names(record.field_name, locale),
            language_name=_names(record.language_name, locale),
            snapshot=snapshot,
        ),
    )
