"""Who may put an item on a shelf or read it: one place for the reader use cases."""

from uuid import UUID

from app.modules.library.domain.access import can_read_content, can_view
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import ItemKind
from app.modules.library.domain.errors import ItemNotFoundError, NotSupportedError
from app.modules.library.domain.reader_errors import FileNotInItemError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor


async def load_visible_item(
    uow: LibraryUnitOfWork, actor: Actor, item_id: UUID
) -> Item:
    """The item when the actor may see it; otherwise `ItemNotFoundError` (404)."""
    item = await uow.items.get(item_id)
    if item is None or not can_view(item, actor):
        raise ItemNotFoundError(support_details=f"item {item_id}")
    return item


async def load_readable_item(
    uow: LibraryUnitOfWork, actor: Actor, item_id: UUID
) -> Item:
    """The item when the actor may open its content.

    Not found or not visible is a 404; a UniLibrary record is `library/not-supported`
    (409); a visible item whose content is closed to the actor is a 404 as well.
    """
    item = await load_visible_item(uow, actor, item_id)
    if item.kind is ItemKind.EXTERNAL:
        raise NotSupportedError(support_details=f"external item {item_id}")
    if not can_read_content(item, actor):
        raise ItemNotFoundError(support_details=f"item {item_id}: content closed")
    return item


def require_file(item: Item, file_id: UUID) -> ItemFile:
    """The file of the item, or `FileNotInItemError` when it is not one of its files."""
    item_file = item.file(file_id)
    if item_file is None:
        raise FileNotInItemError(params={"field": "file_id"})
    return item_file
