"""GET /v1/me/library/markup/{item_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_markup import MarkupResponse


async def get_markup(
    item_id: UUID, library: Library, actor: SignedIn
) -> MarkupResponse:
    """The caller's own markup of the item."""
    markup = await library.reader.get_markup.execute(actor, item_id)
    return (
        MarkupResponse.empty(item_id)
        if markup is None
        else MarkupResponse.from_entity(markup)
    )
