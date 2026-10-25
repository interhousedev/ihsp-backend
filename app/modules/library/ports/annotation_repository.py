"""Port: annotations (owner: the reader area). Every method is scoped to one user."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.enums import AnnotationColor, AnnotationKind
from app.modules.library.domain.reader_annotation import Annotation


@dataclass(frozen=True, slots=True)
class AnnotationCursor:
    """Continue the list after this annotation (most recently changed first)."""

    updated_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class AnnotationFilter:
    """Filters of the annotation list; `query` matches the quote and the note."""

    item_id: UUID | None = None
    kind: AnnotationKind | None = None
    color: AnnotationColor | None = None
    query: str | None = None


class AnnotationRepository(Protocol):
    """Private annotations; nobody reads another user's rows."""

    async def add(self, annotation: Annotation) -> bool:
        """Insert a new annotation; False when the user's client id already exists."""
        ...

    async def save(self, annotation: Annotation) -> None:
        """Update note, colour, timestamps and the deletion mark."""
        ...

    async def get(self, user_id: UUID, annotation_id: UUID) -> Annotation | None:
        """The user's live annotation, or None (also for a deleted one)."""
        ...

    async def get_by_client_id(
        self, user_id: UUID, client_id: UUID
    ) -> Annotation | None:
        """The user's annotation created with this client id, deleted ones too."""
        ...

    async def find_any(self, user_id: UUID, ids: Sequence[UUID]) -> list[Annotation]:
        """The user's annotations whose id or client id is in `ids`, deleted too."""
        ...

    async def list_page(
        self,
        user_id: UUID,
        *,
        filters: AnnotationFilter,
        after: AnnotationCursor | None,
        limit: int,
    ) -> list[Annotation]:
        """Live annotations, most recently changed first, after the cursor."""
        ...

    async def list_for_item(self, user_id: UUID, item_id: UUID) -> list[Annotation]:
        """Live annotations of the user on the item, oldest first.

        The notebooks bridge reads the student's own notes through this method.
        """
        ...

    async def list_for_user(
        self, user_id: UUID, *, item_id: UUID | None
    ) -> list[Annotation]:
        """All live annotations (of one item when given), oldest first."""
        ...

    async def delete_all(self, user_id: UUID) -> int:
        """Delete every annotation of the user, deleted ones too (account closure)."""
        ...
