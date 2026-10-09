"""Private highlights, notes and bookmarks (LIB-8). Pure rules, no I/O."""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import AnnotationColor, AnnotationKind
from app.modules.library.domain.reader_errors import InvalidAnnotationError
from app.shared.ids import new_id

MAX_QUOTE = 1000
MAX_NOTE = 2000
MAX_SYNC_CHANGES = 200


class Unchanged(Enum):
    """Marks a field a patch does not touch (`None` is a real value: clear it)."""

    TOKEN = 0


UNCHANGED = Unchanged.TOKEN


@dataclass(frozen=True, slots=True)
class Annotation:
    """An annotation of one user; nobody else may read it."""

    id: UUID
    user_id: UUID
    item_id: UUID
    file_id: UUID
    kind: AnnotationKind
    locator: dict[str, Any]
    quote: str | None
    note: str | None
    color: AnnotationColor
    client_id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


def clean_text(value: str | None, *, field: str, limit: int) -> str | None:
    """Trimmed text, None when blank; `InvalidAnnotationError` above the limit."""
    text = (value or "").strip()
    if len(text) > limit:
        raise InvalidAnnotationError(params={"field": field, "max": limit})
    return text or None


def build_annotation(
    *,
    user_id: UUID,
    item_id: UUID,
    file_id: UUID,
    kind: AnnotationKind,
    locator: Mapping[str, Any],
    quote: str | None,
    note: str | None,
    color: AnnotationColor,
    client_id: UUID,
    now: datetime,
) -> Annotation:
    """A new annotation with a fresh id."""
    return Annotation(
        id=new_id(),
        user_id=user_id,
        item_id=item_id,
        file_id=file_id,
        kind=kind,
        locator=dict(locator),
        quote=clean_text(quote, field="quote", limit=MAX_QUOTE),
        note=clean_text(note, field="note", limit=MAX_NOTE),
        color=color,
        client_id=client_id,
        created_at=now,
        updated_at=now,
    )


def edit_annotation(
    annotation: Annotation,
    *,
    now: datetime,
    note: str | None | Unchanged = UNCHANGED,
    color: AnnotationColor | None = None,
) -> Annotation:
    """The annotation with a new note and/or colour (same object if unchanged)."""
    new_note = (
        annotation.note
        if isinstance(note, Unchanged)
        else clean_text(note, field="note", limit=MAX_NOTE)
    )
    new_color = color or annotation.color
    if new_note == annotation.note and new_color == annotation.color:
        return annotation
    return dataclasses.replace(
        annotation, note=new_note, color=new_color, updated_at=now
    )


def soft_delete(annotation: Annotation, *, now: datetime) -> Annotation:
    """Mark the annotation deleted (the first time wins)."""
    if annotation.deleted_at is not None:
        return annotation
    return dataclasses.replace(annotation, deleted_at=now, updated_at=now)
