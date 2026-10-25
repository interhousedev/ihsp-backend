"""POST /v1/manage/library/import."""

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import (
    ImportBody,
    ImportResultSchema,
)
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library


async def import_books(
    body: ImportBody,
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
) -> ImportResultSchema:
    """Create draft books from the CSV; rows with errors are listed."""
    result = await library.catalogue.import_books.execute(
        actor, body.csv_file_id, accept_language=accept_language
    )
    return ImportResultSchema.from_view(result)
