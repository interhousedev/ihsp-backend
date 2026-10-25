"""POST /v1/notebooks/{id}/sources/{sid}/reread."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse


async def reread_source(
    notebook_id: UUID, source_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> SourceItemResponse:
    """Extract the source's text again; a source still being read is returned as is."""
    source = await notebooks.reread_source.execute(actor, notebook_id, source_id)
    return SourceItemResponse.from_entity(source)
