"""PATCH /v1/manage/library/collections/{collection_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    ManageCollectionResponse,
    UpdateCollectionBody,
    sent,
)
from app.modules.library.domain.taxonomy_unset import UNSET


async def update_collection(
    collection_id: UUID,
    body: UpdateCollectionBody,
    library: Library,
    actor: LibrarianActor,
) -> ManageCollectionResponse:
    """Change the sent fields; `null` clears the description or the cover."""
    description = body.description.to_dict() if body.description is not None else None
    view = await library.taxonomy.update_collection.execute(
        actor,
        collection_id,
        title=body.title.to_dict() if body.title is not None else UNSET,
        description=sent(body, "description", description),
        cover_file_id=sent(body, "cover_file_id", body.cover_file_id),
        published=body.published if body.published is not None else UNSET,
        item_ids=body.item_ids if body.item_ids is not None else UNSET,
    )
    return ManageCollectionResponse.from_view(view)
