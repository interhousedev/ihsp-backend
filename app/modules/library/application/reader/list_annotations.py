"""Use case: list the actor's own annotations, newest change first (LIB-8)."""

from datetime import datetime
from uuid import UUID

from app.modules.library.application.reader.views import Paged
from app.modules.library.domain.reader_annotation import Annotation
from app.modules.library.ports.annotation_repository import (
    AnnotationCursor,
    AnnotationFilter,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def decode_annotation_cursor(cursor: str | None) -> AnnotationCursor | None:
    """Read a cursor made by `ListAnnotations`; a broken one is a 422."""
    data = decode_cursor(cursor)
    if data is None:
        return None
    try:
        return AnnotationCursor(
            updated_at=datetime.fromisoformat(data["u"]), id=UUID(data["i"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError(
            params={"field": "cursor"}, support_details="malformed cursor"
        ) from exc


class ListAnnotations:
    """One page of the actor's annotations; nobody else's are ever returned."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        *,
        filters: AnnotationFilter | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Paged[Annotation]:
        """Annotations matching the filters, with the cursor of the next page."""
        size = max(1, min(limit, MAX_LIMIT))
        async with self.uow_factory() as uow:
            rows = await uow.annotations.list_page(
                actor.user_id,
                filters=filters or AnnotationFilter(),
                after=decode_annotation_cursor(cursor),
                limit=size + 1,
            )
        page = rows[:size]
        last = page[-1] if len(rows) > size else None
        return Paged(
            items=page,
            next_cursor=(
                encode_cursor({"u": last.updated_at.isoformat(), "i": str(last.id)})
                if last
                else None
            ),
        )
