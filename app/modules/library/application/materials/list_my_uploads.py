"""The caller's own materials with status, reason and place in the queue (LIB-13)."""

from datetime import datetime
from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.materials.views import Slice, UploadRowView
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import decode_cursor, encode_cursor


def decode_position(cursor: str | None) -> tuple[datetime, UUID] | None:
    """The `(created_at, id)` a cursor points after, or None for the first page."""
    data = decode_cursor(cursor)
    if data is None:
        return None
    try:
        return datetime.fromisoformat(data["t"]), UUID(data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError(params={"field": "cursor"}) from exc


class ListMyUploads:
    """Newest first, keyset paged."""

    def __init__(self, *, uow_factory: UowFactory, cards: CardBuilder) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.cards = cards

    async def execute(
        self,
        actor: Actor,
        *,
        status: ItemStatus | None,
        cursor: str | None,
        limit: int,
        locale: str,
    ) -> Slice[UploadRowView]:
        """One page of the caller's materials."""
        after = decode_position(cursor)
        async with self.uow_factory() as uow:
            ids = await uow.moderation.uploads_page(
                actor.user_id, status=status, limit=limit + 1, after=after
            )
            more = len(ids) > limit
            found = await uow.items.get_many(ids[:limit])
            items = [found[item_id] for item_id in ids[:limit] if item_id in found]
            cards = await self.cards.build(uow, items, viewer=actor, locale=locale)
            waiting = [i.id for i in items if i.status is ItemStatus.PENDING_REVIEW]
            places = await uow.moderation.pending_positions(waiting)
        rows = [
            UploadRowView(
                item=card,
                status=item.status,
                reason=item.status_reason,
                review_message=item.status_note,
                queue_position=places.get(item.id),
            )
            for item, card in zip(items, cards, strict=True)
        ]
        return Slice(rows, self._next(items, more))

    @staticmethod
    def _next(items: list[Item], more: bool) -> str | None:
        if not more or not items:
            return None
        last = items[-1]
        return encode_cursor({"t": last.created_at.isoformat(), "id": str(last.id)})
