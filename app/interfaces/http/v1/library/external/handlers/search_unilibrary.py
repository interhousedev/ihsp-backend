"""GET /v1/library/external/unilibrary/search."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, SignedIn
from app.interfaces.http.v1.library.external.schemas_external import (
    UniLibraryAccessFilter,
    UniLibrarySearchResultResponse,
)
from app.modules.library.application.external.search_external import SearchQuery

from fastapi import Query


async def search_unilibrary(
    library: Library,
    actor: SignedIn,
    accept_language: AcceptLanguage = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    subject_id: UUID | None = None,
    field_id: Annotated[int | None, Query(gt=0)] = None,
    type_id: Annotated[int | None, Query(gt=0)] = None,
    language: Annotated[str | None, Query(max_length=20)] = None,
    access: UniLibraryAccessFilter = UniLibraryAccessFilter.ANY,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> UniLibrarySearchResultResponse:
    """Live UniLibrary results as cards that are not stored (`404` while off)."""
    result = await library.external.search.execute(
        actor,
        SearchQuery(
            q=q,
            subject_id=subject_id,
            field_id=field_id,
            type_id=type_id,
            language=language,
            access=access.to_domain(),
            page=page,
            accept_language=accept_language,
        ),
    )
    return UniLibrarySearchResultResponse.from_view(result)
