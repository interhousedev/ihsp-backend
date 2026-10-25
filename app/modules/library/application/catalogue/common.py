"""Pieces the catalogue use cases share: finding an item the caller may see."""

from uuid import UUID

from app.modules.library.domain.access import can_view, is_librarian
from app.modules.library.domain.entities import Item
from app.modules.library.domain.errors import ItemNotFoundError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def anonymous_cards(settings: LibrarySettings) -> bool:
    """True when visitors may see UniLibrary cards (the feature is on and allowed)."""
    return settings.unilibrary_enabled and settings.unilibrary_anonymous_cards


def parse_ref(ref: str) -> UUID | None:
    """The id when `ref` is a UUID, else None (then it is a slug)."""
    try:
        return UUID(ref)
    except ValueError:
        return None


async def load_by_ref(uow: LibraryUnitOfWork, ref: str) -> Item | None:
    """An item by id or slug, whoever may see it."""
    item_id = parse_ref(ref)
    if item_id is not None:
        return await uow.items.get(item_id)
    return await uow.items.get_by_slug(ref)


async def load_visible(
    uow: LibraryUnitOfWork, ref: str, actor: Actor | None, *, cards: bool
) -> Item:
    """The item, or `library/not-found` when missing or not visible to the caller."""
    item = await load_by_ref(uow, ref)
    if item is None or not can_view(item, actor, anonymous_cards=cards):
        raise ItemNotFoundError(support_details=f"item {ref} not visible")
    return item


def require_librarian(actor: Actor) -> None:
    """Book management is for librarians and Administration only."""
    if not is_librarian(actor):
        raise ForbiddenError(support_details="librarian role required")


def clamp_limit(limit: int | None) -> int:
    """A page size between 1 and the maximum; the default when absent."""
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))
