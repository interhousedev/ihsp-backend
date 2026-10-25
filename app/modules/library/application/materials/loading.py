"""Loading a material for its owner or a librarian; strangers get `404` (no IDOR)."""

from uuid import UUID

from app.modules.library.domain.access import can_view, is_librarian, is_owner
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind
from app.modules.library.domain.errors import ItemNotFoundError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor


async def load_material(
    uow: LibraryUnitOfWork, item_id: UUID, *, lock: bool = False
) -> Item:
    """The material, or `ItemNotFoundError` (books and records are not materials)."""
    item = await uow.items.get(item_id, lock=lock)
    if item is None or item.kind is not ItemKind.MATERIAL:
        raise ItemNotFoundError()
    return item


async def load_owned(
    uow: LibraryUnitOfWork, item_id: UUID, actor: Actor, *, lock: bool = False
) -> Item:
    """The actor's own material; anybody else's looks like a missing one."""
    item = await load_material(uow, item_id, lock=lock)
    if not is_owner(item, actor):
        raise ItemNotFoundError()
    return item


async def load_editable(
    uow: LibraryUnitOfWork, item_id: UUID, actor: Actor, *, lock: bool = False
) -> Item:
    """The actor's own material, or any material a librarian may see."""
    item = await load_material(uow, item_id, lock=lock)
    if is_owner(item, actor):
        return item
    if is_librarian(actor) and can_view(item, actor):
        return item
    raise ItemNotFoundError()
