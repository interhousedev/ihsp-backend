"""GET /v1/admin/knowledge."""

from typing import Annotated

from app.interfaces.http.v1.admin_knowledge.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_knowledge.schemas import KnowledgeEntryListResponse

from fastapi import Query


async def list_entries(
    container: ContainerDep,
    actor: AdminActor,
    q: Annotated[str | None, Query(max_length=500)] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeEntryListResponse:
    """List entries: hybrid search with `q`, else the newest changes first."""
    page = await container.knowledge.list_entries.execute(
        q=q, tags=tags or (), limit=limit, offset=offset
    )
    return KnowledgeEntryListResponse.of(
        page.items, page.total, limit, offset, found=bool(q and q.strip())
    )
