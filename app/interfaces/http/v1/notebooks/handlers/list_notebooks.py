"""GET /v1/notebooks."""

from typing import Annotated

from app.interfaces.http.v1.notebooks.deps import Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_common import PageResponse
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookItemResponse
from app.modules.notebooks.application.list_notebooks import DEFAULT_LIMIT, MAX_LIMIT

from fastapi import Query


async def list_notebooks(
    notebooks: Notebooks,
    actor: OwnerActor,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> PageResponse[NotebookItemResponse]:
    """List the student's notebooks, pinned first, then the last opened."""
    page = await notebooks.list_notebooks.execute(
        actor, q=q, cursor=cursor, limit=limit
    )
    return PageResponse(
        items=[NotebookItemResponse.from_entity(n) for n in page.items],
        next_cursor=page.next_cursor,
    )
