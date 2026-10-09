"""Who may see and read an item (doc § 2.3). Pure rules; no I/O.

Everything that lists, finds or opens an item goes through `can_view`, so hidden,
held and unpublished items never leak through search, counts or a direct id.
"""

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ItemStatus, Visibility
from app.shared.actor import Actor, Role

STAFF_ROLES = frozenset({Role.LIBRARIAN, Role.ADMIN})
SIGNED_IN_ROLES = frozenset(
    {Role.STUDENT, Role.TEACHER, Role.LIBRARIAN, Role.ADMIN, Role.LMS_ADMIN}
)
# Statuses an item can be in while a librarian still has something to look at.
REVIEWABLE = frozenset(
    {
        ItemStatus.PENDING_REVIEW,
        ItemStatus.CHANGES_REQUESTED,
        ItemStatus.PUBLISHED,
        ItemStatus.HELD,
        ItemStatus.REJECTED,
        ItemStatus.UNPUBLISHED,
        ItemStatus.GONE,
    }
)


def is_librarian(actor: Actor | None) -> bool:
    """True for a librarian or Administration."""
    return actor is not None and bool(actor.roles & STAFF_ROLES)


def is_signed_in(actor: Actor | None) -> bool:
    """True for any lyceum user (the library has no other signed-in kind)."""
    return actor is not None and bool(actor.roles & SIGNED_IN_ROLES)


def is_owner(item: Item, actor: Actor | None) -> bool:
    """True when the actor uploaded or created the item."""
    return actor is not None and item.owner_id == actor.user_id


def is_listed(item: Item) -> bool:
    """True when ordinary users can find the item in lists and search."""
    return (
        item.status is ItemStatus.PUBLISHED and item.visibility is not Visibility.HIDDEN
    )


def can_view(item: Item, actor: Actor | None, *, anonymous_cards: bool = False) -> bool:
    """May the actor see the item at all (list, search, detail by id)?

    - Owners see their own items in every status (uploads page, edit).
    - Librarians and Administration see everything that left the draft state.
    - Everyone else sees published, non-hidden items; `public` ones also without a
      login (UniLibrary cards only when `anonymous_cards` allows it).
    """
    if is_owner(item, actor):
        return True
    if is_librarian(actor):
        return item.status in REVIEWABLE
    if not is_listed(item):
        return False
    if item.kind is ItemKind.EXTERNAL and item.external and item.external.gone_at:
        return is_signed_in(actor)
    if item.visibility is Visibility.PUBLIC:
        if item.kind is ItemKind.EXTERNAL:
            return is_signed_in(actor) or anonymous_cards
        return True
    return is_signed_in(actor)


def can_read_content(
    item: Item, actor: Actor | None, *, anonymous_cards: bool = False
) -> bool:
    """May the actor open the files or the text of the item?

    Never for UniLibrary records. Outside the owner and librarians, only a published
    item that the actor may view.
    """
    if item.kind is ItemKind.EXTERNAL or not item.files:
        return False
    if not can_view(item, actor, anonymous_cards=anonymous_cards):
        return False
    if is_owner(item, actor) or is_librarian(actor):
        return True
    return item.status is ItemStatus.PUBLISHED


def can_download(
    item: Item, actor: Actor | None, *, anonymous_cards: bool = False
) -> bool:
    """May the actor download the file (the rights basis allows it)?"""
    if not can_read_content(item, actor, anonymous_cards=anonymous_cards):
        return False
    if is_owner(item, actor) or is_librarian(actor):
        return True
    return item.download_allowed


def can_add_to_notebook(item: Item, actor: Actor | None) -> bool:
    """Books and materials only, published, with text, never UniLibrary records."""
    if item.kind is ItemKind.EXTERNAL or not is_signed_in(actor):
        return False
    return can_read_content(item, actor) and item.has_text
