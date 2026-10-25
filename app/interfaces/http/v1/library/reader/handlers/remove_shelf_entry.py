"""DELETE /v1/me/library/shelf/{item_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn


async def remove_shelf_entry(item_id: UUID, library: Library, actor: SignedIn) -> None:
    """Take an item off the shelf (nothing happens when it was not there)."""
    await library.reader.remove_shelf_entry.execute(actor, item_id)
