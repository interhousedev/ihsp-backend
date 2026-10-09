"""GET /v1/notebooks/{id}/sources."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse


async def list_sources(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> list[SourceItemResponse]:
    """List the sources of a notebook in their order."""
    sources = await notebooks.list_sources.execute(actor, notebook_id)
    return [SourceItemResponse.from_entity(s) for s in sources]
