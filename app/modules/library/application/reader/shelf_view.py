"""Turns a shelf entry, its item and its card into the row the app shows."""

import dataclasses

from app.modules.library.application.reader.views import ShelfEntryView
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import can_view, is_listed
from app.modules.library.domain.entities import Item
from app.modules.library.domain.reader_shelf import ShelfEntry
from app.shared.actor import Actor


def is_removed(item: Item, actor: Actor) -> bool:
    """True when the item is no longer offered to ordinary readers.

    Taken down, held, unpublished, hidden or gone items stay on the shelf as
    "removed" rows (the title is kept, doc 3.6).
    """
    return not is_listed(item) or not can_view(item, actor)


def _title_only(card: ItemCardView) -> ItemCardView:
    """A removed row keeps the title and the authors; the rest goes."""
    return dataclasses.replace(
        card,
        cover_url=None,
        description_excerpt=None,
        snippet=None,
        snippet_page=None,
    )


def shelf_entry_view(
    entry: ShelfEntry, item: Item, card: ItemCardView, actor: Actor
) -> ShelfEntryView:
    """The row for one shelf entry."""
    removed = is_removed(item, actor)
    return ShelfEntryView(
        item=_title_only(card) if removed else card,
        state=entry.state,
        finished_at=entry.finished_at,
        updated_at=entry.updated_at,
        removed=removed,
    )
