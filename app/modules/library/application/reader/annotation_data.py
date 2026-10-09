"""The fields a client sends to create or sync an annotation."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import AnnotationColor, AnnotationKind


@dataclass(frozen=True, slots=True)
class AnnotationData:
    """One annotation as the client holds it (`client_id` makes it idempotent)."""

    client_id: UUID
    item_id: UUID
    file_id: UUID
    kind: AnnotationKind
    locator: Mapping[str, Any]
    quote: str | None
    note: str | None
    color: AnnotationColor
