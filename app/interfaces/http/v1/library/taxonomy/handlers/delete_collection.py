"""DELETE /v1/manage/library/collections/{collection_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library


async def delete_collection(
    collection_id: UUID, library: Library, actor: LibrarianActor
) -> None:
    """Delete a collection; its items stay in the library."""
    await library.taxonomy.delete_collection.execute(actor, collection_id)
