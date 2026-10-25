"""PATCH /v1/manage/library/books/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookPatchBody
from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library


async def update_book(
    book_id: UUID,
    body: BookPatchBody,
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Change the fields that were sent."""
    view = await library.catalogue.update_book.execute(
        actor, book_id, body.to_changes(), accept_language=accept_language
    )
    return ItemDetailSchema.from_view(view)
