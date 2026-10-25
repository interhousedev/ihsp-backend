"""POST /v1/notebooks/{id}/discover."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_discover import (
    DiscoverBody,
    DiscoverResponse,
)


async def discover_sources(
    notebook_id: UUID,
    body: DiscoverBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> DiscoverResponse:
    """Search the web for pages to add as sources (nothing is fetched or stored)."""
    view = await notebooks.discover_sources.execute(
        actor, notebook_id, body.query, body.mode
    )
    return DiscoverResponse.from_view(view)
