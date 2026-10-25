"""GET /v1/manage/library/queue."""

from typing import Annotated

from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library
from app.interfaces.http.v1.library.materials.locale import locale_for
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    QueueParams,
    QueueRowResponse,
)
from app.shared.pagination import Page

from fastapi import Query


async def list_queue(
    params: Annotated[QueueParams, Query()],
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
) -> Page[QueueRowResponse]:
    """One tab of the librarian queue, oldest first."""
    locale = await locale_for(library, actor, accept_language)
    page = await library.materials.list_queue.execute(
        actor, params.tab, cursor=params.cursor, limit=params.limit, locale=locale
    )
    return Page[QueueRowResponse](
        items=[QueueRowResponse.from_view(row) for row in page.items],
        next_cursor=page.next_cursor,
    )
