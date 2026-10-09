"""The librarian's table of books (GET /manage/library/books)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.catalogue.common import (
    clamp_limit,
    require_librarian,
)
from app.modules.library.application.catalogue.pages import next_cursor, read_offset
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.enums import (
    ItemStatus,
    Rights,
    TextStatus,
    Visibility,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


@dataclass(frozen=True, slots=True)
class BookRowView:
    """`BookRow` of the TypeScript contract."""

    card: ItemCardView
    status: ItemStatus
    visibility: Visibility
    rights: Rights
    text_status: TextStatus
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BookRowPage:
    """A page of table rows."""

    items: list[BookRowView]
    next_cursor: str | None


class ListBooks:
    """Books in any status, newest change first, with a text filter."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        cards: CardBuilder,
        identity: IdentityDirectory,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity

    async def execute(
        self,
        actor: Actor,
        *,
        q: str | None = None,
        status: ItemStatus | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        accept_language: str | None = None,
    ) -> BookRowPage:
        """One page of the table."""
        require_librarian(actor)
        size = clamp_limit(limit)
        offset = read_offset(cursor)
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            ids = await uow.items.list_books(
                query=q, status=status, limit=size + 1, offset=offset
            )
            found = await uow.items.get_many(ids[:size])
            items = [found[i] for i in ids[:size] if i in found]
            cards = await self.cards.build(uow, items, viewer=actor, locale=locale)
        rows = [
            BookRowView(
                card=card,
                status=item.status,
                visibility=item.visibility,
                rights=item.book.rights if item.book else Rights.OFFICIAL,
                text_status=(
                    item.primary_file.text_status
                    if item.primary_file
                    else TextStatus.NONE
                ),
                updated_at=item.updated_at,
            )
            for card, item in zip(cards, items, strict=True)
        ]
        return BookRowPage(rows, next_cursor(offset, len(rows), len(ids) > size))
