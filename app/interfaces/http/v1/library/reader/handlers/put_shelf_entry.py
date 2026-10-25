"""PUT /v1/me/library/shelf/{item_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import (
    ShelfBody,
    ShelfEntryResponse,
)
from app.modules.library.application.locale import resolve_locale


async def put_shelf_entry(
    item_id: UUID,
    body: ShelfBody,
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
) -> ShelfEntryResponse:
    """Put an item on the shelf or move it (UniLibrary records too, as links)."""
    locale = await resolve_locale(library.core.identity, actor, accept_language)
    view = await library.reader.put_shelf_entry.execute(
        actor, item_id, body.state, locale=locale
    )
    return ShelfEntryResponse.from_view(view)
