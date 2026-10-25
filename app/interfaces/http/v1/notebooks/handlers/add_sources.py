"""POST /v1/notebooks/{id}/sources."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_sources import (
    AddSourcesBody,
    AddSourcesResponse,
)

from fastapi import Request


async def add_sources(
    notebook_id: UUID,
    body: AddSourcesBody,
    request: Request,
    notebooks: Notebooks,
    actor: MemberActor,
) -> AddSourcesResponse:
    """Add up to 20 sources; a refused item is reported, the others are stored."""
    result = await notebooks.add_sources.execute(actor, notebook_id, body.items)
    return AddSourcesResponse.from_result(result, request)
