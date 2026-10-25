"""GET /v1/me/library/shelf?state&cursor."""

from typing import Annotated

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.reader.schemas_reader import ShelfEntryResponse
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.enums import ShelfState
from app.shared.pagination import Page

from fastapi import Query


async def list_shelf(
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
    state: ShelfState | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Page[ShelfEntryResponse]:
    """The shelf, newest change first; taken-down items stay as `removed` rows."""
    locale = await resolve_locale(library.core.identity, actor, accept_language)
    page = await library.reader.list_shelf.execute(
        actor, state=state, cursor=cursor, limit=limit, locale=locale
    )
    return Page(
        items=[ShelfEntryResponse.from_view(v) for v in page.items],
        next_cursor=page.next_cursor,
    )
