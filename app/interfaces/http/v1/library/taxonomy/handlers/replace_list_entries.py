"""PUT /v1/library/reading-lists/{list_id}/items."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, TeachingActor
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    ReadingListDetailResponse,
    ReplaceEntriesBody,
)


async def replace_list_entries(
    list_id: UUID,
    body: ReplaceEntriesBody,
    library: Library,
    actor: TeachingActor,
    accept_language: AcceptLanguage = None,
) -> ReadingListDetailResponse:
    """Replace all entries at once (at most 100, else `422 library/list-too-long`)."""
    view = await library.taxonomy.replace_list_entries.execute(
        actor,
        list_id,
        [item.to_draft() for item in body.items],
        accept_language=accept_language,
    )
    return ReadingListDetailResponse.from_detail(view)
