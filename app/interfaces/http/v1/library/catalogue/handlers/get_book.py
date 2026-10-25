"""GET /v1/manage/library/books/{id}."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookDraftSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library


async def get_book(
    book_id: UUID,
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
) -> BookDraftSchema:
    """The editor's data: detail, saved input and the publish checklist."""
    view = await library.catalogue.get_book_draft.execute(
        actor, book_id, accept_language=accept_language
    )
    return BookDraftSchema.from_view(view)
