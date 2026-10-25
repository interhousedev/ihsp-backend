"""GET /v1/notebooks/{id}/sources/{sid}/passages."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import PageResponse
from app.interfaces.http.v1.notebooks.schemas_sources import PassageItemResponse
from app.modules.notebooks.domain.limits import PASSAGES_PAGE_DEFAULT, PASSAGES_PAGE_MAX

from fastapi import Query


async def list_passages(
    notebook_id: UUID,
    source_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=PASSAGES_PAGE_MAX)] = PASSAGES_PAGE_DEFAULT,
) -> PageResponse[PassageItemResponse]:
    """Return the text of a source in passages, for the source viewer."""
    page = await notebooks.list_passages.execute(
        actor, notebook_id, source_id, cursor=cursor, limit=limit
    )
    return PageResponse(
        items=[PassageItemResponse.from_entity(p) for p in page.items],
        next_cursor=page.next_cursor,
    )
