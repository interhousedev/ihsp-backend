"""DELETE /v1/library/reading-lists/{list_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, TeachingActor


async def delete_reading_list(
    list_id: UUID, library: Library, actor: TeachingActor
) -> None:
    """Delete a list with its entries (its owner, or a librarian)."""
    await library.taxonomy.delete_reading_list.execute(actor, list_id)
