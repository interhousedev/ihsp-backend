"""GET /v1/notebooks/{id}/sources/{sid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_sources import SourceDetailResponse


async def get_source(
    notebook_id: UUID, source_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> SourceDetailResponse:
    """Return a source with its guide and, for a note, its text."""
    source = await notebooks.get_source.execute(actor, notebook_id, source_id)
    return SourceDetailResponse.from_entity(source)
