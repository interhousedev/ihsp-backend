"""GET /v1/notebooks/{id}/search."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_search import SearchResponse
from app.modules.notebooks.domain.limits import (
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    SEARCH_QUERY_MAX_CHARS,
    SEARCH_QUERY_MIN_CHARS,
)

from fastapi import Query


async def search_sources(
    notebook_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    q: Annotated[
        str, Query(min_length=SEARCH_QUERY_MIN_CHARS, max_length=SEARCH_QUERY_MAX_CHARS)
    ],
    limit: Annotated[int, Query(ge=1, le=SEARCH_LIMIT_MAX)] = SEARCH_LIMIT_DEFAULT,
) -> SearchResponse:
    """Find the passages of the notebook's sources that contain the words of `q`."""
    result = await notebooks.search_sources.execute(actor, notebook_id, q, limit)
    return SearchResponse.from_result(result)
