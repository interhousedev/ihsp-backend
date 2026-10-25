"""GET /v1/manage/library/stats?from&to."""

from datetime import date
from typing import Annotated

from app.interfaces.http.v1.library.deps import AcceptLanguage, LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    LibraryStatsResponse,
)

from fastapi import Query


async def get_library_stats(
    library: Library,
    actor: LibrarianActor,
    accept_language: AcceptLanguage = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> LibraryStatsResponse:
    """Opens, readers, queue times and the rest, for the last 30 days by default."""
    view = await library.taxonomy.get_stats.execute(
        actor, start=from_, end=to, accept_language=accept_language
    )
    return LibraryStatsResponse.from_view(view)
