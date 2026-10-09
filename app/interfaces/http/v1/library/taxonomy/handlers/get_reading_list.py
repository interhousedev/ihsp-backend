"""GET /v1/library/reading-lists/{list_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    ReadingListDetailResponse,
)


async def get_reading_list(
    list_id: UUID,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ReadingListDetailResponse:
    """The list with its entries and my read status."""
    view = await library.taxonomy.get_reading_list.execute(
        actor, list_id, accept_language=accept_language
    )
    return ReadingListDetailResponse.from_detail(view)
