"""Library items as notebook sources: who may use them and how pages are cut (LIB-10).

Pure rules with no I/O; the reader in `application/bridge` applies them on every
call, so a held or taken-down item stops being readable at once.
"""

from dataclasses import dataclass, replace

from app.modules.library.domain.access import (
    can_read_content,
    can_view,
    is_signed_in,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ItemStatus
from app.shared.actor import Actor
from app.shared.contracts.library import UnavailableReason

# Statuses an item reaches after it was published; people who could see it before
# are told it is unavailable, everyone else gets "not found".
WITHDRAWN = frozenset({ItemStatus.HELD, ItemStatus.UNPUBLISHED, ItemStatus.GONE})


@dataclass(frozen=True, slots=True)
class PageSlice:
    """A page range cut out of a file's text; `page_starts` are relative to `text`."""

    text: str
    page_starts: tuple[int, ...]
    page_from: int
    page_to: int


def _was_visible(item: Item, actor: Actor) -> bool:
    """True when the actor could see the item if it were still published."""
    if item.status not in WITHDRAWN:
        return False
    return can_view(replace(item, status=ItemStatus.PUBLISHED), actor)


def source_denial(item: Item | None, actor: Actor) -> UnavailableReason | None:
    """Why the actor may not use the item as a source, or None when they may.

    Only published books and materials qualify, never UniLibrary records. Owners and
    librarians get no shortcut: a source must stop working the moment the item is
    held, unpublished or taken down.
    """
    if item is None or not is_signed_in(actor):
        return "not_found"
    if not can_view(item, actor):
        return "unavailable" if _was_visible(item, actor) else "not_found"
    if item.kind is ItemKind.EXTERNAL:
        return "not_supported"
    if item.status is not ItemStatus.PUBLISHED:
        return "unavailable"
    if not item.files:
        return "no_text"
    return None if can_read_content(item, actor) else "unavailable"


def slice_pages(
    text: str,
    page_starts: tuple[int, ...],
    page_from: int | None,
    page_to: int | None,
) -> PageSlice | None:
    """Cut pages `page_from..page_to` (1-based, inclusive) out of the whole text.

    A file without page marks counts as a single page. The range is clamped to the
    pages the file has; None means nothing is left of it.
    """
    starts = page_starts or (0,)
    total = len(starts)
    first = max(page_from or 1, 1)
    last = min(page_to or total, total)
    if first > last:
        return None
    begin = min(starts[first - 1], len(text))
    end = len(text) if last == total else max(min(starts[last], len(text)), begin)
    relative = tuple(
        max(min(s, len(text)) - begin, 0) for s in starts[first - 1 : last]
    )
    return PageSlice(text[begin:end], relative, first, last)
