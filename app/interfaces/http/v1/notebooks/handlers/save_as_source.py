"""POST /v1/notebooks/{id}/artifacts/{aid}/save-as-source."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse


async def save_as_source(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> SourceItemResponse:
    """Add a report to the notebook's sources as a note."""
    source = await notebooks.save_as_source.execute(actor, notebook_id, artifact_id)
    return SourceItemResponse.from_entity(source)
