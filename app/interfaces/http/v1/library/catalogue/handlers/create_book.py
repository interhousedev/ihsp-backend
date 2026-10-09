"""POST /v1/manage/library/books."""

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookInputBody
from app.interfaces.http.v1.library.catalogue.schemas_items import ItemDetailSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library


async def create_book(
    body: BookInputBody,
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
) -> ItemDetailSchema:
    """Create a draft book."""
    view = await library.catalogue.create_book.execute(
        actor, body.to_data(), accept_language=accept_language
    )
    return ItemDetailSchema.from_view(view)
