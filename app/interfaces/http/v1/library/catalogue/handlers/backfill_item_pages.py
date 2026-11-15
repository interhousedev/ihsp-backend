"""POST /v1/manage/library/pages/backfill."""

from app.interfaces.http.v1.library.deps import LibrarianActor, Library


async def backfill_item_pages(library: Library, actor: LibrarianActor) -> None:
    """Start rebuilding the stored page text (folded text, word boxes) of old items."""
    await library.catalogue.backfill_item_pages.request(actor)
