"""POST /v1/manage/library/collections."""

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    CreateCollectionBody,
    ManageCollectionResponse,
)


async def create_collection(
    body: CreateCollectionBody, library: Library, actor: LibrarianActor
) -> ManageCollectionResponse:
    """Create a collection with its items."""
    view = await library.taxonomy.create_collection.execute(
        actor,
        title=body.title.to_dict(),
        description=body.description.to_dict() if body.description else None,
        cover_file_id=body.cover_file_id,
        published=body.published,
        item_ids=body.item_ids,
    )
    return ManageCollectionResponse.from_view(view)
