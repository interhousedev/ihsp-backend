"""GET /v1/manage/library/collections."""

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    ManageCollectionResponse,
)


async def list_manage_collections(
    library: Library, actor: LibrarianActor
) -> list[ManageCollectionResponse]:
    """Every collection, published or not, with all languages."""
    views = await library.taxonomy.list_manage_collections.execute(actor)
    return [ManageCollectionResponse.from_view(view) for view in views]
