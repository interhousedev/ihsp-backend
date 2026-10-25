"""GET /v1/manage/library/books."""

from typing import Annotated

from app.interfaces.http.v1.library.catalogue.schemas_catalogue import BookRowSchema
from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library
from app.modules.library.domain.enums import ItemStatus
from app.shared.pagination import Page

from fastapi import Query


async def list_books(
    library: Library,
    actor: LibrarianActor,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: ItemStatus | None = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    accept_language: AcceptLanguage = None,
) -> Page[BookRowSchema]:
    """The book table: every status, newest change first."""
    page = await library.catalogue.list_books.execute(
        actor,
        q=q,
        status=status,
        cursor=cursor,
        limit=limit,
        accept_language=accept_language,
    )
    return Page[BookRowSchema](
        items=[BookRowSchema.from_view(row) for row in page.items],
        next_cursor=page.next_cursor,
    )
