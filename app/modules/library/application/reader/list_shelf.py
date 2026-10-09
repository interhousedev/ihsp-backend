"""Use case: list the shelf, most recently changed first (LIB-7)."""

from datetime import datetime
from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.reader.shelf_view import shelf_entry_view
from app.modules.library.application.reader.views import Paged, ShelfEntryView
from app.modules.library.domain.enums import ShelfState
from app.modules.library.ports.shelf_repository import ShelfCursor
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def decode_shelf_cursor(cursor: str | None) -> ShelfCursor | None:
    """Read a cursor made by `ListShelf`; a broken one is a 422."""
    data = decode_cursor(cursor)
    if data is None:
        return None
    try:
        return ShelfCursor(
            updated_at=datetime.fromisoformat(data["u"]), item_id=UUID(data["i"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError(
            params={"field": "cursor"}, support_details="malformed cursor"
        ) from exc


class ListShelf:
    """One page of the actor's shelf; entries of vanished items are skipped."""

    def __init__(self, *, uow_factory: UowFactory, cards: CardBuilder) -> None:
        """Store the unit of work factory and the card builder."""
        self.uow_factory = uow_factory
        self.cards = cards

    async def execute(
        self,
        actor: Actor,
        *,
        state: ShelfState | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
        locale: str,
    ) -> Paged[ShelfEntryView]:
        """Entries (with cards) of the shelf, newest change first."""
        size = max(1, min(limit, MAX_LIMIT))
        after = decode_shelf_cursor(cursor)
        async with self.uow_factory() as uow:
            rows = await uow.shelf.list_page(
                actor.user_id, state=state, after=after, limit=size + 1
            )
            page = rows[:size]
            items = await uow.items.get_many([row.item_id for row in page])
            present = [row for row in page if row.item_id in items]
            cards = await self.cards.build(
                uow, [items[row.item_id] for row in present], viewer=actor, locale=locale
            )
        views = [
            shelf_entry_view(row, items[row.item_id], card, actor)
            for row, card in zip(present, cards, strict=True)
        ]
        more = len(rows) > size
        last = page[-1] if more else None
        return Paged(
            items=views,
            next_cursor=(
                encode_cursor({"u": last.updated_at.isoformat(), "i": str(last.item_id)})
                if last
                else None
            ),
        )
