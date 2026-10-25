"""PATCH /v1/notebooks/{id}/sources/{sid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse
from app.interfaces.http.v1.notebooks.schemas_sources import UpdateSourceBody


async def update_source(
    notebook_id: UUID,
    source_id: UUID,
    body: UpdateSourceBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> SourceItemResponse:
    """Rename a source, tick it or edit its text; keys that were not sent are kept."""
    source = await notebooks.update_source.execute(
        actor, notebook_id, source_id, body.model_dump(exclude_unset=True)
    )
    return SourceItemResponse.from_entity(source)
