"""GET /v1/library/reading-lists?subject_id&mine&group_id&status."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    ReadingListCardResponse,
)
from app.modules.library.domain.enums import ListStatus


async def list_reading_lists(
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
    subject_id: UUID | None = None,
    mine: bool = False,
    group_id: UUID | None = None,
    status: ListStatus | None = None,
) -> list[ReadingListCardResponse]:
    """Lists the caller may open (students: the lists of their group and school)."""
    views = await library.taxonomy.list_reading_lists.execute(
        actor,
        subject_id=subject_id,
        mine=mine,
        group_id=group_id,
        status=status,
        accept_language=accept_language,
    )
    return [ReadingListCardResponse.from_view(view) for view in views]
