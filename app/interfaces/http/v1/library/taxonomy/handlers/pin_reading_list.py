"""PUT /v1/library/reading-lists/{list_id}/pin."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    PinReadingListBody,
    ReadingListDetailResponse,
)


async def pin_reading_list(
    list_id: UUID,
    body: PinReadingListBody,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ReadingListDetailResponse:
    """Pin or unpin a list (librarians and Administration; others get 403)."""
    view = await library.taxonomy.pin_reading_list.execute(
        actor, list_id, pinned=body.pinned, accept_language=accept_language
    )
    return ReadingListDetailResponse.from_detail(view)
