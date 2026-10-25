"""POST /v1/manage/library/books/{id}/publish | unpublish | takedown."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookActionBody
from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library


async def publish_book(
    book_id: UUID,
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Publish; `422 library/rights-incomplete` lists what is missing."""
    view = await library.catalogue.publish_book.execute(
        actor, book_id, accept_language=accept_language
    )
    return ItemDetailSchema.from_view(view)


async def unpublish_book(
    book_id: UUID,
    library: Library,
    actor: LibrarianActor,
    body: BookActionBody | None = None,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Withdraw a published book."""
    view = await library.catalogue.unpublish_book.execute(
        actor,
        book_id,
        reason=body.reason if body else None,
        accept_language=accept_language,
    )
    return ItemDetailSchema.from_view(view)


async def takedown_book(
    book_id: UUID,
    library: Library,
    actor: LibrarianActor,
    body: BookActionBody | None = None,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Take a book down; the reason is required and kept."""
    view = await library.catalogue.takedown_book.execute(
        actor,
        book_id,
        reason=body.reason if body else None,
        accept_language=accept_language,
    )
    return ItemDetailSchema.from_view(view)
