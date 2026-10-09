"""PATCH /v1/library/reading-lists/{list_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, TeachingActor
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    ReadingListDetailResponse,
    UpdateReadingListBody,
)


async def update_reading_list(
    list_id: UUID,
    body: UpdateReadingListBody,
    library: Library,
    actor: TeachingActor,
    accept_language: AcceptLanguage = None,
) -> ReadingListDetailResponse:
    """Change the sent fields of a list (its owner, or a librarian)."""
    view = await library.taxonomy.update_reading_list.execute(
        actor, list_id, body.to_changes(), accept_language=accept_language
    )
    return ReadingListDetailResponse.from_detail(view)
