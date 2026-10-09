"""POST /v1/manage/library/books/{id}/files."""

from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookFileBody
from app.interfaces.http.v1.library.catalogue.schemas_items import ItemFileSchema
from app.interfaces.http.v1.library.deps import LibrarianActor, Library


async def attach_book_file(
    book_id: UUID, body: BookFileBody, library: Library, actor: LibrarianActor
) -> ItemFileSchema:
    """Attach an uploaded file; text extraction runs in the background."""
    view = await library.catalogue.attach_book_file.execute(
        actor,
        book_id,
        file_id=body.file_id,
        file_format=body.format,
        is_primary=body.is_primary,
    )
    return ItemFileSchema.from_view(view)
