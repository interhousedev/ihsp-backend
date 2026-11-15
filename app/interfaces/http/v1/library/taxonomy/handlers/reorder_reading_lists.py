"""PUT /v1/library/reading-lists/order."""

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_lists import (
    ReorderReadingListsBody,
)


async def reorder_reading_lists(
    body: ReorderReadingListsBody, library: Library, actor: SignedIn
) -> None:
    """Set the sequence of lists (librarians and Administration; others get 403)."""
    await library.taxonomy.reorder_reading_lists.execute(actor, body.ids)
